"""纯文本抽取器：将内联文本或本地文本文件转为 ExtractionResult。

不调用 LLM，不做版式解析；仅负责读取原始字符串，后续由 TextNormalizer 统一规整。
"""

from __future__ import annotations

from pathlib import Path

from label_agent.perception.extractors.base import AttachmentRef, ExtractionResult

_EXTRACTOR_VERSION = "v1"


class TextExtractor:
    """纯文本附件抽取器。

    支持两种来源：
    1. AttachmentRef.inline_text（payload.text 等内联字段）；
    2. 本地文件路径（.txt 等），以 UTF-8 读取，解码失败时回退到替换策略。
    """

    def extract(self, attachment: AttachmentRef) -> ExtractionResult:
        """从文本附件提取原始字符串并标记成功模态为 text。

        当既无内联文本、本地路径又不存在或为空时，返回 failed_modality=text，
        由编排层决定是否整单失败。
        """
        versions = {"text_extractor": _EXTRACTOR_VERSION}
        if attachment.inline_text is not None:
            text = attachment.inline_text
            if not text.strip():
                return ExtractionResult(
                    failed_modality="text",
                    perception_versions=versions,
                    error_message="内联文本为空",
                )
            return ExtractionResult(
                text=text,
                successful_modality="text",
                perception_versions=versions,
            )

        path = Path(attachment.ref)
        if not path.exists() or not path.is_file():
            return ExtractionResult(
                failed_modality="text",
                perception_versions=versions,
                error_message=f"文本文件不存在: {attachment.ref}",
            )
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            return ExtractionResult(
                failed_modality="text",
                perception_versions=versions,
                error_message=f"文本文件内容为空: {attachment.ref}",
            )
        return ExtractionResult(
            text=text,
            successful_modality="text",
            perception_versions=versions,
        )
