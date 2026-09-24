"""S4 商品感知、类目快照、召回与双模型判断的中间模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductImageObservation(_StrictModel):
    asset_id: str
    source_ref: str
    ocr_text: str = ""
    vision_text: str = ""
    ocr_succeeded: bool = False
    vision_succeeded: bool = False


class ProductPerception(_StrictModel):
    title: str = ""
    images: list[ProductImageObservation] = Field(default_factory=list)
    failed_image_refs: list[str] = Field(default_factory=list)


class ProductAnalysis(_StrictModel):
    product_name: str = ""
    product_type: str = ""
    brand: str = ""
    attributes: list[str] = Field(default_factory=list)
    usage: str = ""
    image_features: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    summary: str = ""
    modality_conflict: bool = False
    conflict_description: str = ""

    def retrieval_text(self, title: str) -> str:
        """标题置顶，保证标题和图片冲突时检索侧也遵循标题优先。"""
        parts = [title, self.product_name, self.product_type, self.usage]
        parts.extend(self.keywords)
        parts.extend(self.attributes)
        return " ".join(part.strip() for part in parts if part and part.strip())


class ProductCategoryRecord(_StrictModel):
    category_id: str
    category_name: str
    level: Literal[1, 2]
    parent_category_id: str | None = None
    parent_category_name: str | None = None
    taxonomy_version: str
    status: Literal["active"] = "active"
    category_description: str = ""
    aliases: list[str] = Field(default_factory=list)
    include_products: list[str] = Field(default_factory=list)
    exclude_products: list[str] = Field(default_factory=list)
    positive_keywords: list[str] = Field(default_factory=list)
    negative_keywords: list[str] = Field(default_factory=list)
    classification_rules: list[str] = Field(default_factory=list)

    @property
    def path(self) -> str:
        if self.level == 1:
            return self.category_name
        return f"{self.parent_category_name}/{self.category_name}"

    @property
    def index_text(self) -> str:
        values = [
            self.path,
            self.category_name,
            self.category_description,
            *self.aliases,
            *self.include_products,
            *self.positive_keywords,
        ]
        return " ".join(value for value in values if value)


class ProductCategoryCandidate(_StrictModel):
    category: ProductCategoryRecord
    fused_score: float = Field(ge=0.0)
    retrieval_sources: list[str] = Field(default_factory=list)


class ProductClassificationDecision(_StrictModel):
    decision: Literal["classified", "unknown"]
    level2_category_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    matched_features: list[str] = Field(default_factory=list)
    model_name: str = ""

    @model_validator(mode="after")
    def validate_selected_id(self) -> ProductClassificationDecision:
        if self.decision == "classified" and not self.level2_category_id:
            raise ValueError("classified 必须返回 level2_category_id")
        if self.decision == "unknown" and self.level2_category_id is not None:
            raise ValueError("unknown 不得返回 level2_category_id")
        return self


class ProductReviewDecision(_StrictModel):
    decision: Literal["classified", "unknown"]
    level2_category_id: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""
    reason_codes: list[str] = Field(default_factory=list)
    model_name: str = ""

    @model_validator(mode="after")
    def validate_selected_id(self) -> ProductReviewDecision:
        if self.decision == "classified" and not self.level2_category_id:
            raise ValueError("classified 必须返回 level2_category_id")
        if self.decision == "unknown" and self.level2_category_id is not None:
            raise ValueError("unknown 不得返回 level2_category_id")
        return self
