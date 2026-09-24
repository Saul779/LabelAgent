"""S1/S2 多模态抽取器包：将文本/图片/PDF/DOCX/DOC 统一抽取为中间结果。

各抽取器互不依赖业务场景，由 CertificateContentLoader 按 InputRouter 路由结果调度，
最终聚合为 ContentBundle，供生成式提议只消费 normalized_text。
"""

from label_agent.perception.extractors.base import AttachmentKind, AttachmentRef, ExtractionResult
from label_agent.perception.extractors.doc_extractor import DocExtractor
from label_agent.perception.extractors.docx_extractor import DocxExtractor
from label_agent.perception.extractors.hybrid_image_extractor import HybridImageExtractor
from label_agent.perception.extractors.image_vision_extractor import ImageVisionExtractor
from label_agent.perception.extractors.pdf_extractor import PdfExtractor
from label_agent.perception.extractors.text_extractor import TextExtractor

__all__ = [
    "AttachmentKind",
    "AttachmentRef",
    "DocExtractor",
    "DocxExtractor",
    "ExtractionResult",
    "ImageVisionExtractor",
    "HybridImageExtractor",
    "PdfExtractor",
    "TextExtractor",
]
