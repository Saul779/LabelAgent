"""结构化证据引用 EvidenceRef（§3.4），替代自由文本证据。

规则引擎判定证据真实性时只信任 EvidenceRef 校验结果；`evidence` 自由文本
字段仅用于人工审核台展示，不参与规则判定。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class TextEvidenceRef(BaseModel):
    """文本模态证据引用：定位到原文的字符区间与引用内容哈希。"""

    type: Literal["text"] = "text"
    asset_id: str
    char_start: int
    char_end: int
    quote: str
    content_hash: str


class ImageEvidenceRef(BaseModel):
    """图片模态证据引用：定位到图片的 bbox 区域及可选 OCR 文本片段。"""

    type: Literal["image"] = "image"
    asset_id: str
    bbox: list[float]
    ocr_span: str | None = None
    image_hash: str


class VideoFrameEvidenceRef(BaseModel):
    """指向某视频帧证据的引用。"""

    type: Literal["video_frame"] = "video_frame"
    asset_id: str
    frame_id: str
    start_ms: int
    end_ms: int
    bbox: list[float] | None = None


class AsrEvidenceRef(BaseModel):
    """指向某 ASR 片段证据的引用。"""

    type: Literal["asr"] = "asr"
    asset_id: str
    start_ms: int
    end_ms: int
    quote: str


EvidenceRef = TextEvidenceRef | ImageEvidenceRef | VideoFrameEvidenceRef | AsrEvidenceRef


class EvidenceBundle(BaseModel):
    """一次 Job 收集的证据集合。"""

    refs: list[TextEvidenceRef | ImageEvidenceRef | VideoFrameEvidenceRef | AsrEvidenceRef]
