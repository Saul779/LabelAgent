"""PDF 抽取器：优先抽取文本层，扫描件降级为页渲染 + 视觉理解。

数字 PDF：用 PyMuPDF 按页抽取文字并合并。
扫描 PDF：当全文过短时，将前若干页渲染为 PNG data URL，复用 ImageVisionExtractor。
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path

import fitz  # PyMuPDF

from label_agent.domain.models.content import ImageArtifact, OcrSegment, PerceptionTextBlock
from label_agent.perception.extractors.base import AttachmentKind, AttachmentRef, ExtractionResult
from label_agent.perception.extractors.hybrid_image_extractor import HybridImageExtractor
from label_agent.perception.extractors.image_vision_extractor import ImageVisionExtractor
from label_agent.utils.hashing import sha256_hex

logger = logging.getLogger(__name__)

_EXTRACTOR_VERSION = "v1"
_DEFAULT_MAX_PAGES = 10
_DEFAULT_VISION_MAX_PAGES = 3
_DEFAULT_TEXT_MIN_CHARS = 40


class PdfExtractor:
    """PDF 文档抽取器（文本层优先，扫描件视觉降级）。

    处理策略：
    1. 打开本地 PDF，最多处理 max_pages 页的文本层；
    2. 若合并文本长度 >= text_min_chars，视为数字 PDF，模态标记 pdf_text；
    3. 否则将前 vision_max_pages 页渲染为图，调用 ImageVisionExtractor，模态标记 pdf_vision；
    4. 远程 URI 的 PDF 当前不下载（避免隐式 SSRF 拉文件），记 failed_modality=pdf。
    """

    def __init__(
        self,
        image_vision_extractor: ImageVisionExtractor | HybridImageExtractor | None = None,
        *,
        max_pages: int = _DEFAULT_MAX_PAGES,
        vision_max_pages: int = _DEFAULT_VISION_MAX_PAGES,
        text_min_chars: int = _DEFAULT_TEXT_MIN_CHARS,
    ) -> None:
        """注入可选视觉抽取器与页数/文本阈值配置。

        image_vision_extractor 为空且需要视觉降级时，将返回 pdf 失败模态，
        避免在无 LLM 能力时静默跳过扫描件。
        """
        self._image_vision = image_vision_extractor
        self._max_pages = max(1, max_pages)
        self._vision_max_pages = max(1, vision_max_pages)
        self._text_min_chars = max(0, text_min_chars)

    async def extract(
        self, attachment: AttachmentRef, *, context_hint: str = ""
    ) -> ExtractionResult:
        """抽取单个 PDF 附件的可读文本（必要时走视觉降级）。

        成功路径写入 text / image_artifacts / successful_modality；
        打开失败、无文本且无法视觉降级时写入 failed_modality=pdf。
        """
        versions = {"pdf_extractor": _EXTRACTOR_VERSION}
        path = Path(attachment.ref)
        if attachment.ref.startswith(("http://", "https://")):
            return ExtractionResult(
                failed_modality="pdf",
                perception_versions=versions,
                error_message="暂不支持直接拉取远程 PDF，请先下载到本地路径",
            )
        if not path.exists() or not path.is_file():
            return ExtractionResult(
                failed_modality="pdf",
                perception_versions=versions,
                error_message=f"PDF 文件不存在: {attachment.ref}",
            )

        try:
            doc = fitz.open(str(path))
        except Exception as exc:  # noqa: BLE001
            logger.warning("打开 PDF 失败 path=%s err=%s", path, exc)
            return ExtractionResult(
                failed_modality="pdf",
                perception_versions=versions,
                error_message=f"无法打开 PDF: {exc}",
            )

        truncation_flags: list[str] = []
        try:
            page_count = doc.page_count
            pages_to_read = min(page_count, self._max_pages)
            if page_count > self._max_pages:
                truncation_flags.append("pdf_pages_truncated")

            page_texts: list[str] = []
            for index in range(pages_to_read):
                page = doc.load_page(index)
                page_texts.append((page.get_text("text") or "").strip())
            merged = "\n\n".join(t for t in page_texts if t).strip()

            if len(merged) >= self._text_min_chars:
                return ExtractionResult(
                    text=merged,
                    successful_modality="pdf_text",
                    truncation_flags=truncation_flags,
                    perception_versions=versions,
                )

            return await self._extract_via_vision(
                doc=doc,
                path=path,
                context_hint=context_hint,
                base_versions=versions,
                truncation_flags=truncation_flags,
                weak_text=merged,
            )
        finally:
            doc.close()

    async def _extract_via_vision(
        self,
        *,
        doc: fitz.Document,
        path: Path,
        context_hint: str,
        base_versions: dict[str, str],
        truncation_flags: list[str],
        weak_text: str,
    ) -> ExtractionResult:
        """文本层过短时，将前若干页渲染为图并调用视觉抽取器。

        多页描述按页标题拼接；渲染页同时写入 image_artifacts 便于溯源。
        无视觉能力或全部页视觉失败时，回退为 failed_modality=pdf。
        """
        if self._image_vision is None:
            return ExtractionResult(
                text=weak_text,
                failed_modality="pdf",
                truncation_flags=list(truncation_flags),
                perception_versions=base_versions,
                error_message="PDF 文本层过短且未配置视觉抽取器，无法处理扫描件",
            )

        page_count = doc.page_count
        pages_to_render = min(page_count, self._vision_max_pages)
        if page_count > self._vision_max_pages:
            truncation_flags = list(truncation_flags) + ["pdf_vision_pages_truncated"]

        descriptions: list[str] = []
        artifacts: list[ImageArtifact] = []
        ocr_segments: list[OcrSegment] = []
        perception_text_blocks: list[PerceptionTextBlock] = []
        successful_modalities: list[str] = []
        failed_modalities: list[str] = []
        versions = dict(base_versions)
        last_error: str | None = None

        for index in range(pages_to_render):
            page = doc.load_page(index)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            png_bytes = pix.tobytes("png")
            b64 = base64.b64encode(png_bytes).decode("ascii")
            data_url = f"data:image/png;base64,{b64}"
            image_hash = sha256_hex(png_bytes)
            asset_id = f"{path.stem}-p{index + 1}"
            page_artifact = ImageArtifact(
                asset_id=asset_id,
                uri=str(path),
                image_hash=image_hash,
                width=pix.width,
                height=pix.height,
            )
            page_ref = AttachmentRef(
                kind=AttachmentKind.IMAGE,
                ref=data_url,
                source_key=f"pdf:{path.name}:page:{index + 1}",
            )
            hint = context_hint
            if weak_text:
                hint = f"{context_hint}\nPDF弱文本层：{weak_text}".strip()
            vision_result = await self._image_vision.extract(page_ref, context_hint=hint)
            versions.update(vision_result.perception_versions)
            successful_modalities.extend(vision_result.successful_modalities)
            failed_modalities.extend(vision_result.failed_modalities)
            original_asset_id = (
                vision_result.image_artifacts[0].asset_id
                if vision_result.image_artifacts
                else asset_id
            )
            if vision_result.image_artifacts:
                page_artifact = vision_result.image_artifacts[0].model_copy(
                    update={
                        "asset_id": asset_id,
                        "uri": str(path),
                        "image_hash": image_hash,
                    }
                )
            artifacts.append(page_artifact)
            ocr_segments.extend(
                segment.model_copy(update={"asset_id": asset_id})
                for segment in vision_result.ocr_segments
            )
            perception_text_blocks.extend(
                block.model_copy(update={"asset_id": asset_id})
                for block in vision_result.perception_text_blocks
            )
            if vision_result.successful_modality and vision_result.text.strip():
                page_text = vision_result.text.strip().replace(original_asset_id, asset_id)
                descriptions.append(f"[第{index + 1}页]\n{page_text}")
            else:
                last_error = vision_result.error_message or "页面视觉理解失败"

        if not descriptions:
            return ExtractionResult(
                text=weak_text,
                image_artifacts=artifacts,
                ocr_segments=ocr_segments,
                perception_text_blocks=perception_text_blocks,
                failed_modality="pdf",
                failed_modalities=failed_modalities,
                truncation_flags=truncation_flags,
                perception_versions=versions,
                error_message=last_error or "扫描 PDF 视觉理解未产出有效文本",
            )

        return ExtractionResult(
            text="\n\n".join(descriptions),
            image_artifacts=artifacts,
            ocr_segments=ocr_segments,
            perception_text_blocks=perception_text_blocks,
            successful_modality="pdf_hybrid",
            successful_modalities=successful_modalities,
            failed_modalities=failed_modalities,
            truncation_flags=truncation_flags,
            perception_versions=versions,
        )
