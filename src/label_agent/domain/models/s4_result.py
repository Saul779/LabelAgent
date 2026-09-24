"""S4 商品打标的领域模型与最终回执契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductCategoryRef(_StrictModel):
    """最终结果中的稳定类目引用。"""

    category_id: str
    name: str


class ProductCategoryPath(_StrictModel):
    """唯一一级/二级类目路径。"""

    level1: ProductCategoryRef
    level2: ProductCategoryRef


class ProductSearchTerms(_StrictModel):
    """只随自动通过结果发布的商品搜索词。"""

    core_terms: list[str] = Field(default_factory=list, max_length=10)
    attribute_terms: list[str] = Field(default_factory=list, max_length=20)
    scene_terms: list[str] = Field(default_factory=list, max_length=20)
    long_tail_queries: list[str] = Field(default_factory=list, max_length=15)
    synonym_terms: list[str] = Field(default_factory=list, max_length=10)
    feature_terms: list[str] = Field(default_factory=list, max_length=15)
    search_summary: str = ""
    keyword_quality_score: float = Field(ge=0.0, le=1.0)


class ProductCategorySuggestion(_StrictModel):
    """现有类目疑似缺失时返回的候选建议；Agent 不直接创建类目。"""

    suggested_level1_name: str | None = None
    suggested_level2_name: str
    reason: str
    supporting_features: list[str] = Field(default_factory=list)


class ProductModelRun(_StrictModel):
    """单次分类/复核模型调用的审计信息。"""

    model_name: str
    model_alias: str
    prompt_version: str
    confidence: float = Field(ge=0.0, le=1.0)
    decision: Literal["classified", "unknown"]
    level2_category_id: str | None = None


class ProductLabelResult(_StrictModel):
    """S4 最终结果。

    `decision` 是业务决策；MQ 外层 status 只表达技术处理是否完成。
    unknown/need_review 都是结构化成功结果，不通过异常表示。
    """

    product_id: str
    scene: Literal["S4"] = "S4"
    taxonomy_version: str
    category: ProductCategoryPath | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    decision: Literal["classified", "unknown", "need_review"]
    need_manual_review: bool
    reason_codes: list[str] = Field(default_factory=list)
    reason: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    search_terms: ProductSearchTerms | None = None
    category_suggestion: ProductCategorySuggestion | None = None
    model_runs: dict[Literal["classifier", "reviewer"], ProductModelRun]
    degraded_modalities: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_decision_contract(self) -> ProductLabelResult:
        """强制业务决策、类目、审核标记和搜索词保持一致。"""
        if self.decision == "classified":
            if self.category is None:
                raise ValueError("classified 必须包含唯一类目路径")
            if self.need_manual_review:
                raise ValueError("classified 不得标记人工审核")
        else:
            if not self.need_manual_review:
                raise ValueError("unknown/need_review 必须标记人工审核")
            if self.search_terms is not None:
                raise ValueError("unknown/need_review 不得发布搜索词")
        if self.decision == "unknown" and self.category is not None:
            raise ValueError("unknown 不得包含正式类目路径")
        return self

    def to_receipt_payload(self) -> dict:
        """序列化为 MQ 回执 payload，保留显式 null 字段以稳定契约。"""
        return self.model_dump(mode="json")
