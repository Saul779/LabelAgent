"""T1 首版文本+图片感知，正文优先、图片补充。"""

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
from label_agent.perception.extractors.hybrid_image_extractor import HybridImageExtractor
from label_agent.perception.extractors.image_vision_extractor import ImageVisionExtractor
from label_agent.perception.extractors.text_extractor import TextExtractor
from label_agent.perception.image.image_probe import ImageProbe
from label_agent.perception.image.ocr import OcrEngine
from label_agent.perception.input_router import InputRouter
from label_agent.perception.media_guard import MediaGuard
from label_agent.perception.text.normalizer import TextNormalizer

logger = logging.getLogger(__name__)


class T1InputError(NonRetryableError):
    """T1 输入缺失或首版不支持时抛出。"""

    error_code = "T1_INVALID_INPUT"


class T1ContentLoader:
    """只接收文本与图片，并将正文放在图片感知结果之前。"""

    _AUTHORITATIVE_TEXT_KEYS = ("description", "body", "text", "content", "raw_text")

    def __init__(
        self,
        text_normalizer: TextNormalizer,
        media_guard: MediaGuard | None,
        llm_gateway: LlmGateway,
        prompt_manager: PromptManager,
        *,
        vision_prompt_version: str = "t1-vision-v1",
        input_router: InputRouter | None = None,
        ocr_engine: OcrEngine | None = None,
        image_probe: ImageProbe | None = None,
        image_ocr_options: dict | None = None,
    ) -> None:
        self._text_normalizer = text_normalizer
        self._router = input_router or InputRouter()
        self._text_extractor = TextExtractor()
        vision = ImageVisionExtractor(
            llm_gateway=llm_gateway,
            prompt_manager=prompt_manager,
            media_guard=media_guard,
            vision_prompt_version=vision_prompt_version,
            scene="t1",
        )
        options = image_ocr_options or {}
        self._image_extractor = HybridImageExtractor(
            image_vision_extractor=vision,
            ocr_engine=ocr_engine or OcrEngine(),
            media_guard=media_guard,
            image_probe=image_probe
            or ImageProbe(max_pixels=int(options.get("max_pixels", 40_000_000))),
            dense_region_count=int(options.get("dense_region_count", 12)),
            dense_area_ratio=float(options.get("dense_area_ratio", 0.12)),
            small_text_height_ratio=float(options.get("small_text_height_ratio", 0.018)),
            minimum_ocr_confidence=float(options.get("minimum_ocr_confidence", 0.45)),
            ocr_context_max_chars=int(options.get("ocr_context_max_chars", 12_000)),
        )

    async def build(self, ctx: JobContext) -> ContentBundle:
        payload = ctx.payload or {}
        routed = self._router.route(payload)
        unsupported = [
            ref.kind.value
            for ref in routed
            if ref.kind not in {AttachmentKind.TEXT, AttachmentKind.IMAGE}
        ]
        if unsupported:
            kinds = ", ".join(_unique_preserve(unsupported))
            raise T1InputError(f"T1 首版只支持文本和图片，不支持: {kinds}")

        authoritative_parts = self._collect_payload_text(payload)
        text_results: list[ExtractionResult] = []
        image_refs: list[AttachmentRef] = []
        for ref in routed:
            if ref.kind == AttachmentKind.IMAGE:
                image_refs.append(ref)
            elif ref.kind == AttachmentKind.TEXT and ref.source_key.startswith("attachments["):
                text_results.append(self._text_extractor.extract(ref))

        title = payload.get("title")
        if isinstance(title, str) and title.strip():
            authoritative_parts.append(f"标题：{title.strip()}")
        for result in text_results:
            if result.text.strip():
                authoritative_parts.append(f"正文附件：{result.text.strip()}")

        context_hint = "\n".join(authoritative_parts)
        image_results: list[ExtractionResult] = []
        for ref in image_refs:
            result = await self._image_extractor.extract(ref, context_hint=context_hint)
            image_results.append(result)
            if result.failed_modality:
                logger.info(
                    "T1 图片感知失败 source=%s err=%s", ref.source_key, result.error_message
                )

        if not authoritative_parts and not image_results:
            raise T1InputError("T1 输入至少需要非空文本或一张图片")
        return self._aggregate(authoritative_parts, text_results + image_results)

    def _collect_payload_text(self, payload: dict) -> list[str]:
        parts: list[str] = []
        labels = {
            "description": "描述",
            "body": "正文",
            "text": "正文",
            "content": "正文",
            "raw_text": "正文",
        }
        seen: set[str] = set()
        for key in self._AUTHORITATIVE_TEXT_KEYS:
            value = payload.get(key)
            if not isinstance(value, str) or not value.strip():
                continue
            cleaned = value.strip()
            if cleaned in seen:
                continue
            seen.add(cleaned)
            parts.append(f"{labels[key]}（优先）：{cleaned}")
        return parts

    def _aggregate(
        self, authoritative_parts: list[str], results: list[ExtractionResult]
    ) -> ContentBundle:
        image_text: list[str] = []
        image_artifacts: list[ImageArtifact] = []
        ocr_segments: list[OcrSegment] = []
        text_blocks: list[PerceptionTextBlock] = []
        successful: list[str] = []
        failed: list[str] = []
        truncations: list[str] = []
        versions: dict[str, str] = {"input_router": self._router.version}

        for result in results:
            if result.text.strip() and (
                result.successful_modality == "image"
                or "image_ocr" in result.successful_modalities
                or "image_vision" in result.successful_modalities
            ):
                image_text.append(result.text.strip())
            image_artifacts.extend(result.image_artifacts)
            ocr_segments.extend(result.ocr_segments)
            text_blocks.extend(result.perception_text_blocks)
            if result.successful_modality:
                successful.append(result.successful_modality)
            successful.extend(result.successful_modalities)
            if result.failed_modality:
                failed.append(result.failed_modality)
            failed.extend(result.failed_modalities)
            truncations.extend(result.truncation_flags)
            versions.update(result.perception_versions)

        sections: list[str] = []
        if authoritative_parts:
            sections.append("[描述与正文：冲突时以本节为准]\n" + "\n".join(authoritative_parts))
        if image_text:
            sections.append("[图片补充信息：不得覆盖描述与正文]\n" + "\n\n".join(image_text))
        if not sections:
            raise T1InputError("T1 文本为空且图片未产出可识别内容")

        normalized = self._text_normalizer.normalize("\n\n".join(sections))
        if normalized.truncated:
            truncations.append("text_truncated")
        versions["text_normalizer"] = "v1"
        return ContentBundle(
            normalized_text=normalized.text,
            content_hash=normalized.content_hash,
            image_artifacts=image_artifacts,
            ocr_segments=ocr_segments,
            perception_text_blocks=text_blocks,
            successful_modalities=_unique_preserve(successful),
            failed_modalities=_unique_preserve(failed),
            truncation_flags=_unique_preserve(truncations),
            perception_versions=versions,
        )


def _unique_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
