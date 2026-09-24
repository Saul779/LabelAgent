"""ContentBundleBuilder：按任务资源类型并行调度感知，聚合为 ContentBundle（§5.1.2）。

资源驱动（无 Feature Flag）：
- 文本 → TextExtractor + TextNormalizer
- 任务图片 → Vision（不做 OCR）
- 视频 → 抽帧后仅 OCR + 必做 ASR（无音轨则跳过 ASR）
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.content import (
    AsrSegment,
    ContentBundle,
    ImageArtifact,
    OcrSegment,
    VideoFrameArtifact,
)
from label_agent.perception.asr.transcriber import AsrTranscriber
from label_agent.perception.extractors.base import AttachmentKind, AttachmentRef, ExtractionResult
from label_agent.perception.extractors.image_vision_extractor import ImageVisionExtractor
from label_agent.perception.extractors.text_extractor import TextExtractor
from label_agent.perception.image.ocr import OcrEngine
from label_agent.perception.input_router import InputRouter
from label_agent.perception.media_guard import MediaGuard
from label_agent.perception.text.normalizer import TextNormalizer
from label_agent.perception.video.frame_sampler import SampledFrame, VideoFrameSampler

logger = logging.getLogger(__name__)


@dataclass
class _ModalityResult:
    """单附件感知中间结果，供聚合阶段合并。"""

    text: str = ""
    image_artifacts: list[ImageArtifact] = field(default_factory=list)
    video_frame_artifacts: list[VideoFrameArtifact] = field(default_factory=list)
    ocr_segments: list[OcrSegment] = field(default_factory=list)
    asr_segments: list[AsrSegment] = field(default_factory=list)
    successful_modalities: list[str] = field(default_factory=list)
    failed_modalities: list[str] = field(default_factory=list)
    truncation_flags: list[str] = field(default_factory=list)
    perception_versions: dict[str, str] = field(default_factory=dict)
    error_message: str | None = None
    cleanup_paths: list[Path] = field(default_factory=list)


class ContentBundleBuilder:
    """S3 多模态感知编排器：有什么资源就感知什么。"""

    def __init__(
        self,
        media_guard: MediaGuard | None,
        text_normalizer: TextNormalizer,
        ocr_engine: OcrEngine,
        frame_sampler: VideoFrameSampler,
        asr_transcriber: AsrTranscriber,
        image_vision: ImageVisionExtractor,
        input_router: InputRouter | None = None,
    ) -> None:
        """注入媒体护栏、文本规整、OCR/抽帧/ASR 与任务图 Vision。"""
        self._media_guard = media_guard
        self._text_normalizer = text_normalizer
        self._ocr_engine = ocr_engine
        self._frame_sampler = frame_sampler
        self._asr_transcriber = asr_transcriber
        self._image_vision = image_vision
        self._router = input_router or InputRouter()
        self._text_extractor = TextExtractor()

    async def build(self, ctx: JobContext) -> ContentBundle:
        """并行处理各模态；失败写入 failed_modalities，不得静默跳过。"""
        payload = ctx.payload or {}
        attachments = self._router.route(payload)
        if not attachments:
            raise NonRetryableError("S3 输入缺少可识别附件（text / image / video / attachments）")

        context_hint = self._collect_context_hint(attachments)
        results = await asyncio.gather(
            *[self._dispatch(item, context_hint=context_hint) for item in attachments]
        )
        try:
            return self._aggregate(list(results))
        finally:
            for result in results:
                _cleanup_paths(result.cleanup_paths)

    async def _dispatch(self, attachment: AttachmentRef, *, context_hint: str) -> _ModalityResult:
        """按附件类型调度对应感知路径。"""
        if attachment.kind == AttachmentKind.TEXT:
            return self._from_extraction(self._text_extractor.extract(attachment))
        if attachment.kind == AttachmentKind.IMAGE:
            extraction = await self._image_vision.extract(attachment, context_hint=context_hint)
            return self._from_extraction(extraction)
        if attachment.kind == AttachmentKind.VIDEO:
            return await self._perceive_video(attachment)
        return _ModalityResult(
            failed_modalities=[attachment.kind.value],
            error_message=f"S3 感知暂不处理附件类型: {attachment.kind.value}",
        )

    async def _perceive_video(self, attachment: AttachmentRef) -> _ModalityResult:
        """视频：抽帧 → 仅 OCR；并行 ASR（无音轨跳过）。"""
        versions = {
            "video_frame_sampler": self._frame_sampler.version,
            "ocr_engine": self._ocr_engine.version,
            "asr_transcriber": self._asr_transcriber.version,
        }
        cleanup: list[Path] = []
        frames_result, asr_result = await asyncio.gather(
            self._frame_sampler.sample(attachment.ref, media_guard=self._media_guard),
            self._asr_transcriber.transcribe(
                attachment.ref,
                asset_id=_video_asset_id(attachment.ref),
                media_guard=self._media_guard,
            ),
            return_exceptions=True,
        )

        failed: list[str] = []
        errors: list[str] = []
        frames: list[SampledFrame] = []
        if isinstance(frames_result, BaseException):
            logger.error(
                "视频抽帧失败 ref=%s err=%s",
                attachment.ref,
                frames_result,
                exc_info=frames_result,
            )
            failed.append("video_ocr")
            errors.append(f"frame:{frames_result}")
        else:
            frames = frames_result
            for frame in frames:
                cleanup.append(frame.path)
            if frames:
                cleanup.append(frames[0].path.parent)

        asr_segments: list[AsrSegment] = []
        if isinstance(asr_result, BaseException):
            logger.error(
                "视频 ASR 失败 ref=%s err=%s",
                attachment.ref,
                asr_result,
                exc_info=asr_result,
            )
            failed.append("asr")
            errors.append(f"asr:{asr_result}")
            asr_outcome_skipped = False
        else:
            asr_segments = list(asr_result.segments)
            asr_outcome_skipped = asr_result.skipped_no_audio
            if asr_outcome_skipped:
                versions["asr_status"] = "skipped_no_audio"
            elif asr_segments:
                versions["asr_status"] = "ok"
            else:
                versions["asr_status"] = "empty_transcript"

        ocr_segments: list[OcrSegment] = []
        ocr_texts: list[str] = []
        if frames:
            try:
                for frame in frames:
                    segs = await self._ocr_engine.recognize(
                        str(frame.path),
                        asset_id=f"{frame.artifact.asset_id}:{frame.artifact.frame_id}",
                    )
                    ocr_segments.extend(segs)
                    ocr_texts.extend(seg.text for seg in segs if seg.text.strip())
            except Exception as exc:  # noqa: BLE001
                logger.exception("视频帧 OCR 失败 ref=%s", attachment.ref)
                failed.append("video_ocr")
                errors.append(f"ocr:{exc}")
                frames = []

        successful: list[str] = []
        text_parts: list[str] = []
        frame_artifacts = [f.artifact.model_copy(update={"uri": None}) for f in frames]
        if frames and "video_ocr" not in failed:
            successful.append("video_ocr")
            if ocr_texts:
                text_parts.append("\n".join(ocr_texts))
        if not isinstance(asr_result, BaseException):
            if asr_segments:
                successful.append("asr")
                text_parts.append("\n".join(seg.text for seg in asr_segments))
            elif not asr_outcome_skipped:
                successful.append("asr")

        if not successful and failed:
            return _ModalityResult(
                failed_modalities=_unique_preserve(failed),
                perception_versions=versions,
                error_message="; ".join(errors),
                cleanup_paths=cleanup,
            )

        return _ModalityResult(
            text="\n\n".join(text_parts),
            video_frame_artifacts=frame_artifacts,
            ocr_segments=ocr_segments,
            asr_segments=asr_segments,
            successful_modalities=successful,
            failed_modalities=_unique_preserve(failed),
            perception_versions=versions,
            error_message="; ".join(errors) if errors else None,
            cleanup_paths=cleanup,
        )

    def _from_extraction(self, extraction: ExtractionResult) -> _ModalityResult:
        """将 ExtractionResult 转为内部中间结果。"""
        result = _ModalityResult(
            text=extraction.text,
            image_artifacts=list(extraction.image_artifacts),
            ocr_segments=list(extraction.ocr_segments),
            perception_versions=dict(extraction.perception_versions),
            truncation_flags=list(extraction.truncation_flags),
            error_message=extraction.error_message,
        )
        if extraction.successful_modality:
            result.successful_modalities.append(extraction.successful_modality)
        if extraction.failed_modality:
            result.failed_modalities.append(extraction.failed_modality)
        return result

    def _collect_context_hint(self, attachments: list[AttachmentRef]) -> str:
        """收集内联文本作为 Vision 补充上下文。"""
        hints: list[str] = []
        for item in attachments:
            if item.kind == AttachmentKind.TEXT and item.inline_text:
                stripped = item.inline_text.strip()
                if stripped:
                    hints.append(stripped)
        return "\n".join(hints)

    def _aggregate(self, results: list[_ModalityResult]) -> ContentBundle:
        """合并各附件感知结果为 ContentBundle。"""
        text_parts: list[str] = []
        image_artifacts: list[ImageArtifact] = []
        video_frames: list[VideoFrameArtifact] = []
        ocr_segments: list[OcrSegment] = []
        asr_segments: list[AsrSegment] = []
        successful: list[str] = []
        failed: list[str] = []
        truncations: list[str] = []
        versions: dict[str, str] = {"input_router": self._router.version}

        for result in results:
            if result.text.strip():
                text_parts.append(result.text.strip())
            image_artifacts.extend(result.image_artifacts)
            video_frames.extend(result.video_frame_artifacts)
            ocr_segments.extend(result.ocr_segments)
            asr_segments.extend(result.asr_segments)
            successful.extend(result.successful_modalities)
            failed.extend(result.failed_modalities)
            truncations.extend(result.truncation_flags)
            versions.update(result.perception_versions)

        if not text_parts:
            detail = "; ".join(
                f"{m}:{r.error_message}"
                for r in results
                for m in r.failed_modalities
                if r.error_message
            )
            raise NonRetryableError("S3 感知未产出有效文本" + (f"（{detail}）" if detail else ""))

        merged_raw = "\n\n".join(text_parts)
        normalized = self._text_normalizer.normalize(merged_raw)
        if normalized.truncated:
            truncations.append("text_truncated")
        versions["text_normalizer"] = "v1"
        versions["ocr_engine"] = versions.get("ocr_engine", self._ocr_engine.version)

        return ContentBundle(
            normalized_text=normalized.text,
            content_hash=normalized.content_hash,
            image_artifacts=image_artifacts,
            video_frame_artifacts=video_frames,
            ocr_segments=ocr_segments,
            asr_segments=asr_segments,
            successful_modalities=_unique_preserve(successful),
            failed_modalities=_unique_preserve(failed),
            truncation_flags=_unique_preserve(truncations),
            perception_versions=versions,
        )


def _unique_preserve(values: list[str]) -> list[str]:
    """去除空串并保序去重。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _video_asset_id(ref: str) -> str:
    """从视频引用生成简短 asset_id。"""
    name = Path(ref).name
    return name or "video"


def _cleanup_paths(paths: list[Path]) -> None:
    """清理抽帧临时文件与目录（忽略缺失）。"""
    files = [p for p in paths if p.is_file()]
    dirs = [p for p in paths if p.is_dir()]
    for path in files:
        path.unlink(missing_ok=True)
    for path in dirs:
        shutil.rmtree(path, ignore_errors=True)
