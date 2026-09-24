"""S1/S2 轻量感知编排：InputRouter + 多格式 Extractor → ContentBundle。

与 S3 的 ContentBundleBuilder 分离：不依赖视频/ASR；PDF 扫描件通过页渲染复用视觉 Prompt。
下游 GenerativeProposer 仅消费 normalized_text，本模块负责把多模态输入收敛为统一文本。
"""

from __future__ import annotations

import logging

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.content import (
    ContentBundle,
    ImageArtifact,
    OcrSegment,
    PerceptionTextBlock,
)
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.perception.extractors.base import AttachmentKind, AttachmentRef, ExtractionResult
from label_agent.perception.extractors.doc_extractor import DocExtractor
from label_agent.perception.extractors.docx_extractor import DocxExtractor
from label_agent.perception.extractors.hybrid_image_extractor import HybridImageExtractor
from label_agent.perception.extractors.image_vision_extractor import ImageVisionExtractor
from label_agent.perception.extractors.pdf_extractor import PdfExtractor
from label_agent.perception.extractors.text_extractor import TextExtractor
from label_agent.perception.image.image_probe import ImageProbe
from label_agent.perception.image.ocr import OcrEngine
from label_agent.perception.input_router import InputRouter
from label_agent.perception.media_guard import MediaGuard
from label_agent.perception.text.normalizer import TextNormalizer

logger = logging.getLogger(__name__)


class CertificateContentLoader:
    """S1/S2 感知入口编排器。

    流程：
    1. InputRouter 将 payload 归一为 AttachmentRef 列表；
    2. 按 kind 分发到 Text / Image / PDF / DOCX / DOC 抽取器；
    3. 合并各 ExtractionResult 的文本与产物，经 TextNormalizer 规整；
    4. 组装 ContentBundle（含 successful/failed modalities 与 perception_versions）。

    兼容旧行为：仅 text 或仅 image 的 payload 仍可正常产出 ContentBundle。
    """

    def __init__(
        self,
        text_normalizer: TextNormalizer,
        media_guard: MediaGuard | None,
        llm_gateway: LlmGateway,
        prompt_manager: PromptManager,
        *,
        vision_prompt_version: str,
        scene: str,
        input_router: InputRouter | None = None,
        ocr_engine: OcrEngine | None = None,
        image_probe: ImageProbe | None = None,
        image_ocr_options: dict | None = None,
    ) -> None:
        """注入文本规整、媒体护栏、LLM、Prompt 配置，并装配默认抽取器链。

        vision_prompt_version / scene 用于图片与扫描 PDF 的视觉理解模板定位。
        input_router 可注入以便测试替换；默认使用正式 InputRouter。
        """
        self._text_normalizer = text_normalizer
        self._media_guard = media_guard
        self._llm_gateway = llm_gateway
        self._prompt_manager = prompt_manager
        self._vision_prompt_version = vision_prompt_version
        self._scene = scene
        self._router = input_router or InputRouter()

        self._text_extractor = TextExtractor()
        self._image_vision_extractor = ImageVisionExtractor(
            llm_gateway=llm_gateway,
            prompt_manager=prompt_manager,
            media_guard=media_guard,
            vision_prompt_version=vision_prompt_version,
            scene=scene,
        )
        options = image_ocr_options or {}
        resolved_probe = image_probe or ImageProbe(
            max_pixels=int(options.get("max_pixels", 40_000_000))
        )
        self._image_extractor = HybridImageExtractor(
            image_vision_extractor=self._image_vision_extractor,
            ocr_engine=ocr_engine or OcrEngine(),
            media_guard=media_guard,
            image_probe=resolved_probe,
            dense_region_count=int(options.get("dense_region_count", 12)),
            dense_area_ratio=float(options.get("dense_area_ratio", 0.12)),
            small_text_height_ratio=float(options.get("small_text_height_ratio", 0.018)),
            minimum_ocr_confidence=float(options.get("minimum_ocr_confidence", 0.45)),
            ocr_context_max_chars=int(options.get("ocr_context_max_chars", 12_000)),
        )
        self._docx_extractor = DocxExtractor()
        self._doc_extractor = DocExtractor(self._docx_extractor)
        self._pdf_extractor = PdfExtractor(image_vision_extractor=self._image_extractor)

    async def build(self, ctx: JobContext) -> ContentBundle:
        """根据 JobContext.payload 构建 ContentBundle。

        支持纯文本、图片、PDF、DOCX、DOC 及 attachments 混合输入。
        若全部附件失败或没有任何可路由附件，抛出 NonRetryableError。
        """
        payload = ctx.payload or {}
        attachments = self._router.route(payload)
        if not attachments:
            raise NonRetryableError(
                "S1/S2 输入缺少可识别附件（text / image / pdf / docx / doc / attachments）"
            )

        context_hint = self._collect_context_hint(attachments)
        results: list[ExtractionResult] = []
        for attachment in attachments:
            result = await self._dispatch(attachment, context_hint=context_hint)
            results.append(result)
            if result.failed_modality:
                logger.info(
                    "附件抽取失败 kind=%s source=%s err=%s",
                    attachment.kind.value,
                    attachment.source_key,
                    result.error_message,
                )

        return self._aggregate(results)

    async def _dispatch(self, attachment: AttachmentRef, *, context_hint: str) -> ExtractionResult:
        """按附件类型调度对应抽取器并返回 ExtractionResult。

        图片与 PDF 为异步（可能调用 LLM）；文本/DOCX/DOC 为同步包装为协程结果。
        """
        if attachment.kind == AttachmentKind.TEXT:
            return self._text_extractor.extract(attachment)
        if attachment.kind == AttachmentKind.IMAGE:
            return await self._image_extractor.extract(attachment, context_hint=context_hint)
        if attachment.kind == AttachmentKind.VIDEO:
            return ExtractionResult(
                failed_modality="video",
                error_message="S1/S2 不支持视频附件，请走 S3 感知管线",
            )
        if attachment.kind == AttachmentKind.PDF:
            return await self._pdf_extractor.extract(attachment, context_hint=context_hint)
        if attachment.kind == AttachmentKind.DOCX:
            return self._docx_extractor.extract(attachment)
        if attachment.kind == AttachmentKind.DOC:
            return self._doc_extractor.extract(attachment)
        return ExtractionResult(
            failed_modality="unknown",
            error_message=f"未支持的附件类型: {attachment.kind}",
        )

    def _collect_context_hint(self, attachments: list[AttachmentRef]) -> str:
        """从文本类附件收集补充上下文，供图片/扫描 PDF 视觉 Prompt 使用。

        仅拼接内联文本，避免在路由阶段同步读大文件；文件型文本由 TextExtractor 正式抽取。
        """
        hints: list[str] = []
        for item in attachments:
            if item.kind == AttachmentKind.TEXT and item.inline_text:
                stripped = item.inline_text.strip()
                if stripped:
                    hints.append(stripped)
        return "\n".join(hints)

    def _aggregate(self, results: list[ExtractionResult]) -> ContentBundle:
        """将多次抽取结果合并为单一 ContentBundle。

        合并规则：
        - 文本按结果顺序拼接，块之间空行分隔，再统一 TextNormalizer；
        - image_artifacts / ocr_segments 列表追加；
        - successful/failed modalities 与 truncation_flags 去重保序；
        - perception_versions 合并，并始终写入 input_router 与 text_normalizer 版本。
        若没有任何成功文本，抛出 NonRetryableError。
        """
        text_parts: list[str] = []
        image_artifacts: list[ImageArtifact] = []
        ocr_segments: list[OcrSegment] = []
        perception_text_blocks: list[PerceptionTextBlock] = []
        successful: list[str] = []
        failed: list[str] = []
        truncations: list[str] = []
        versions: dict[str, str] = {"input_router": self._router.version}

        for result in results:
            if result.text.strip():
                text_parts.append(result.text.strip())
            image_artifacts.extend(result.image_artifacts)
            ocr_segments.extend(result.ocr_segments)
            perception_text_blocks.extend(result.perception_text_blocks)
            if result.successful_modality:
                successful.append(result.successful_modality)
            successful.extend(result.successful_modalities)
            if result.failed_modality:
                failed.append(result.failed_modality)
            failed.extend(result.failed_modalities)
            truncations.extend(result.truncation_flags)
            versions.update(result.perception_versions)

        if not text_parts:
            detail = "; ".join(
                f"{r.failed_modality}:{r.error_message}" for r in results if r.failed_modality
            )
            raise NonRetryableError(
                "S1/S2 感知未产出有效文本" + (f"（{detail}）" if detail else "")
            )

        merged_raw = "\n\n".join(text_parts)
        normalized = self._text_normalizer.normalize(merged_raw)
        if normalized.truncated:
            truncations.append("text_truncated")
        versions["text_normalizer"] = "v1"

        return ContentBundle(
            normalized_text=normalized.text,
            content_hash=normalized.content_hash,
            image_artifacts=image_artifacts,
            ocr_segments=ocr_segments,
            perception_text_blocks=perception_text_blocks,
            successful_modalities=_unique_preserve(successful),
            failed_modalities=_unique_preserve(failed),
            truncation_flags=_unique_preserve(truncations),
            perception_versions=versions,
        )


def _unique_preserve(values: list[str]) -> list[str]:
    """去除空串并保序去重，用于 modalities / truncation_flags 列表整理。"""
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered
