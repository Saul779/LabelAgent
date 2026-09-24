"""S3 场景输出契约 ContentLabelResult（§3.3.1）。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


class CategoryResult(BaseModel):
    """S3 输出中的一级/二级分类结果，含置信度与证据引用。"""

    category_id: str
    name: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[dict] = Field(default_factory=list)


class TagResult(BaseModel):
    """S3 输出中的单条内容标签结果，携带命中来源、模型分与最终置信度。"""

    tag_id: str
    canonical_tag_id: str
    display_name: str
    name_type: str  # standard | alias
    source: str  # matched | created
    model_score: float
    final_confidence: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[dict] = Field(default_factory=list)
    vector_state: str  # PENDING | READY | FAILED


class ContentLabelResult(BaseModel):
    """S3 内容打标场景的最终输出契约，承载分类与标签结果列表。"""

    schema_version: str = "1.0"
    biz_id: str
    data_version: int | None = None
    result_revision: int
    dictionary_snapshot_version: str
    model_run_id: str
    prompt_version: str
    policy_version: str
    primary_category: CategoryResult
    secondary_category: CategoryResult | None = None
    tags: list[TagResult] = Field(default_factory=list)
    degraded_modalities: list[str] = Field(default_factory=list)
    perception_versions: dict[str, str] = Field(default_factory=dict)

    def to_receipt_payload(self) -> dict:
        """转换为可直接写入统一回执 payload 的 JSON 兼容字典。"""
        return self.model_dump(mode="json")

    @field_validator("tags")
    @classmethod
    def _validate_tag_count_and_order(cls, tags: list[TagResult]) -> list[TagResult]:
        """校验 tags 数量不超过上限，且必须按 final_confidence 降序排列（§3.3.1）。"""
        if len(tags) > 5:
            raise ValueError("tags 长度必须为 0~5（§3.3.1）")
        scores = [t.final_confidence for t in tags]
        if scores != sorted(scores, reverse=True):
            raise ValueError("tags 必须按 final_confidence 降序排列（§3.3.1）")
        return tags
