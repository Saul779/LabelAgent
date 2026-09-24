"""DOCX 抽取器：使用 python-docx 提取段落与表格文字。

仅处理 Office Open XML（.docx）；老版 .doc 由 DocExtractor 负责，不在本模块解析。
"""

from __future__ import annotations

import logging
from pathlib import Path

from docx import Document

from label_agent.perception.extractors.base import AttachmentRef, ExtractionResult

logger = logging.getLogger(__name__)

_EXTRACTOR_VERSION = "v1"


class DocxExtractor:
    """DOCX 文档文本抽取器。

    按文档顺序拼接段落文本与表格单元格文本，单元格之间以制表符分隔，
    行之间换行，块之间空行分隔，便于后续 TextNormalizer 规整。
    """

    def extract(self, attachment: AttachmentRef) -> ExtractionResult:
        """从本地 .docx 文件抽取可读正文。

        文件不存在、损坏或抽取结果为空时返回 failed_modality=docx；
        成功则 successful_modality=docx，并记录 docx_extractor 版本。
        """
        versions = {"docx_extractor": _EXTRACTOR_VERSION}
        path = Path(attachment.ref)
        if not path.exists() or not path.is_file():
            return ExtractionResult(
                failed_modality="docx",
                perception_versions=versions,
                error_message=f"DOCX 文件不存在: {attachment.ref}",
            )
        try:
            document = Document(str(path))
            chunks: list[str] = []
            for paragraph in document.paragraphs:
                text = (paragraph.text or "").strip()
                if text:
                    chunks.append(text)
            for table in document.tables:
                rows: list[str] = []
                for row in table.rows:
                    cells = [(cell.text or "").strip() for cell in row.cells]
                    cells = [c for c in cells if c]
                    if cells:
                        rows.append("\t".join(cells))
                if rows:
                    chunks.append("\n".join(rows))
            merged = "\n\n".join(chunks).strip()
        except Exception as exc:  # noqa: BLE001 — 第三方解析错误统一记失败模态
            logger.warning("DOCX 解析失败 path=%s err=%s", path, exc)
            return ExtractionResult(
                failed_modality="docx",
                perception_versions=versions,
                error_message=f"DOCX 解析失败: {exc}",
            )

        if not merged:
            return ExtractionResult(
                failed_modality="docx",
                perception_versions=versions,
                error_message=f"DOCX 未抽取到有效文本: {attachment.ref}",
            )
        return ExtractionResult(
            text=merged,
            successful_modality="docx",
            perception_versions=versions,
        )
