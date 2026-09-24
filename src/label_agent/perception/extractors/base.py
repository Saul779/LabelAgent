"""多模态抽取公共模型：附件类型、附件引用与单次抽取结果。

本模块只定义跨抽取器共享的数据结构，不包含具体解析逻辑。
CertificateContentLoader 依赖这些类型完成路由调度与结果聚合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from label_agent.domain.models.content import ImageArtifact, OcrSegment, PerceptionTextBlock


class AttachmentKind(str, Enum):
    """附件媒体类型枚举，供 InputRouter 分类与抽取器分发使用。

    取值说明：
    - TEXT：纯文本（payload 内联或 .txt 等）
    - IMAGE：位图/照片，走视觉理解（S3 任务图）或 S1/S2 vision
    - VIDEO：视频，S3 抽帧 OCR + ASR；S1/S2 不支持
    - PDF：PDF 文档（数字文本层或扫描件）
    - DOCX：Office Open XML 文档
    - DOC：老版 Word 二进制格式（默认要求上游转码）
    """

    TEXT = "text"
    IMAGE = "image"
    VIDEO = "video"
    PDF = "pdf"
    DOCX = "docx"
    DOC = "doc"


@dataclass(frozen=True)
class AttachmentRef:
    """一次待处理附件的规范化引用。

    由 InputRouter 从 JobContext.payload 解析得到，抽取器只依赖本结构，
    不再直接解析异构 payload 字段，从而保证路由与抽取职责分离。
    """

    kind: AttachmentKind
    """附件类型，决定调度哪个 Extractor。"""

    ref: str
    """本地路径、HTTP(S) URI、data URL，或内联文本占位标识。"""

    inline_text: str | None = None
    """当 kind=TEXT 且文本直接来自 payload 字段时，存放原始字符串；否则为 None。"""

    source_key: str = ""
    """来源 payload 字段名（如 text / image_path / attachments[0]），便于排障。"""


@dataclass
class ExtractionResult:
    """单个抽取器对一份附件的处理结果。

    成功时至少应提供可并入 normalized_text 的 text，或明确的 failed_modality；
    失败不得静默丢弃，须由编排层写入 ContentBundle.failed_modalities。
    """

    text: str = ""
    """本附件贡献的可读文本（文档正文或图片描述）。"""

    image_artifacts: list[ImageArtifact] = field(default_factory=list)
    """本附件关联的图片证据（原图或 PDF 渲染页）。"""

    ocr_segments: list[OcrSegment] = field(default_factory=list)
    """可选 OCR 片段；数字文档直接抽文本时可为空。"""

    perception_text_blocks: list[PerceptionTextBlock] = field(default_factory=list)
    """按 OCR / Vision 等来源保存的感知文本块。"""

    successful_modality: str | None = None
    """成功模态标签，如 text / image / pdf_text / pdf_vision / docx。"""

    successful_modalities: list[str] = field(default_factory=list)
    """允许混合提取器同时报告 image_ocr 与 image_vision。"""

    failed_modality: str | None = None
    """失败模态标签；与 successful_modality 互斥使用（允许仅其一有值）。"""

    failed_modalities: list[str] = field(default_factory=list)
    """混合提取器的部分失败模态；整体仍可成功。"""

    truncation_flags: list[str] = field(default_factory=list)
    """本附件处理过程中的截断标记（如 pdf_pages_truncated）。"""

    perception_versions: dict[str, str] = field(default_factory=dict)
    """本抽取器及其依赖组件的版本号，供结果回溯。"""

    error_message: str | None = None
    """失败时的人类可读原因，供日志与排障使用。"""
