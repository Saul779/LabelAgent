"""DOC（老版 Word）抽取器：默认不原生解析二进制 .doc。

策略：
1. 若文件实际为 ZIP/OOXML（误用 .doc 后缀的 docx），转交 DocxExtractor；
2. 否则标记 failed_modality=doc，提示上游转为 DOCX 后再提交。

不在本进程内依赖 LibreOffice，避免部署环境脆弱性。
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

from label_agent.perception.extractors.base import AttachmentKind, AttachmentRef, ExtractionResult
from label_agent.perception.extractors.docx_extractor import DocxExtractor

logger = logging.getLogger(__name__)

_EXTRACTOR_VERSION = "v1"
_ZIP_MAGIC = b"PK\x03\x04"


class DocExtractor:
    """老版 .doc 附件处理入口。

    优先识别“伪 .doc”（实为 DOCX）并委托 DocxExtractor；
    真正的 OLE 复合文档不落本地转码，返回失败模态供编排层记录。
    """

    def __init__(self, docx_extractor: DocxExtractor | None = None) -> None:
        """注入可选的 DocxExtractor；未注入时内部创建默认实例。"""
        self._docx_extractor = docx_extractor or DocxExtractor()

    def extract(self, attachment: AttachmentRef) -> ExtractionResult:
        """处理 .doc 引用：可转 DOCX 则抽取，否则明确失败并给出转码建议。

        失败不会抛出业务异常（除非调用方另行要求），以便多附件场景下
        其它模态仍可成功贡献文本。
        """
        versions = {"doc_extractor": _EXTRACTOR_VERSION}
        path = Path(attachment.ref)
        if not path.exists() or not path.is_file():
            return ExtractionResult(
                failed_modality="doc",
                perception_versions=versions,
                error_message=f"DOC 文件不存在: {attachment.ref}",
            )

        header = path.read_bytes()[:8]
        if header.startswith(_ZIP_MAGIC) and zipfile.is_zipfile(path):
            logger.info("检测到 .doc 后缀实为 OOXML，委托 DocxExtractor path=%s", path)
            result = self._docx_extractor.extract(
                AttachmentRef(
                    kind=AttachmentKind.DOCX,
                    ref=str(path),
                    source_key=attachment.source_key,
                )
            )
            result.perception_versions = {
                **versions,
                **result.perception_versions,
            }
            if result.successful_modality:
                result.successful_modality = "doc"
            elif result.failed_modality:
                result.failed_modality = "doc"
            return result

        return ExtractionResult(
            failed_modality="doc",
            perception_versions=versions,
            error_message=(
                "暂不支持原生 .doc 二进制解析，请先转换为 .docx 后重新提交"
                f"（path={attachment.ref}）"
            ),
        )
