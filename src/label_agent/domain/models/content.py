"""感知产物 ContentBundle（§5.1.2）。

不持久化，不等同于 content_vector（A008 已确认不建设）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ImageArtifact(BaseModel):
    """图片感知产物元数据（资产 ID、URI、哈希）。"""

    asset_id: str
    uri: str
    image_hash: str
    width: int | None = None
    height: int | None = None
    dpi_x: float | None = None
    dpi_y: float | None = None
    orientation: int | None = None
    sharpness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    text_region_count: int = Field(default=0, ge=0)
    text_area_ratio: float = Field(default=0.0, ge=0.0, le=1.0)
    text_density: str | None = None
    processing_route: str | None = None


class VideoFrameArtifact(BaseModel):
    """视频抽帧产物元数据。"""

    asset_id: str
    frame_id: str
    start_ms: int
    end_ms: int
    uri: str | None = None
    """本地帧路径（可选，供 OCR/证据回溯）。"""


class OcrSegment(BaseModel):
    """OCR 文本片段及其定位信息。"""

    asset_id: str
    text: str
    bbox: list[float] = Field(default_factory=list)
    normalized_bbox: list[float] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    reading_order: int | None = Field(default=None, ge=0)


class PerceptionTextBlock(BaseModel):
    """感知文本及其来源；OCR 与 Vision 文本均可作为后续摘录来源。"""

    asset_id: str
    source_type: str
    text: str
    perception_version: str = ""


class AsrSegment(BaseModel):
    """ASR 转写文本片段及时间戳。"""

    asset_id: str
    start_ms: int
    end_ms: int
    text: str


class ContentBundle(BaseModel):
    """感知阶段聚合产物：规整文本、多模态产物、成功/失败模态与版本信息。"""

    normalized_text: str = ""
    image_artifacts: list[ImageArtifact] = Field(default_factory=list)
    video_frame_artifacts: list[VideoFrameArtifact] = Field(default_factory=list)
    ocr_segments: list[OcrSegment] = Field(default_factory=list)
    perception_text_blocks: list[PerceptionTextBlock] = Field(default_factory=list)
    asr_segments: list[AsrSegment] = Field(default_factory=list)
    successful_modalities: list[str] = Field(default_factory=list)
    failed_modalities: list[str] = Field(default_factory=list)
    truncation_flags: list[str] = Field(default_factory=list)
    content_hash: str = ""
    perception_versions: dict[str, str] = Field(default_factory=dict)
