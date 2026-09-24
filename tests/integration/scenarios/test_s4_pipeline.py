"""S4 管线的自动通过、待审核与 unknown 集成测试（模型/Embedding 脚本化）。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from label_agent.core.context import JobContext
from label_agent.domain.models.s4_product import (
    ProductAnalysis,
    ProductCategoryCandidate,
    ProductClassificationDecision,
    ProductPerception,
    ProductReviewDecision,
)
from label_agent.domain.models.s4_result import (
    ProductCategorySuggestion,
    ProductSearchTerms,
)
from label_agent.infrastructure.taxonomy.product_taxonomy import ProductTaxonomyImporter
from label_agent.scenarios.s4_product.pipeline import S4ProductPipeline

_WORKBOOK = Path(__file__).resolve().parents[3] / "docs" / "在场电商平台商品分类信息.xlsx"


class _Perception:
    async def perceive(self, ctx):
        _ = ctx
        return ProductPerception(title="新鲜苹果水果")


class _Retriever:
    def __init__(self, candidate):
        self.candidate = candidate

    @property
    def taxonomy_version(self):
        return self.candidate.category.taxonomy_version

    async def retrieve(self, query):
        assert query
        return [self.candidate]


class _Inference:
    classifier_alias = "primary"
    reviewer_alias = "reviewer"
    classifier_prompt = "s4-classify-v1"
    reviewer_prompt = "s4-review-v1"

    def __init__(self, category_id: str, mode: str):
        self.category_id = category_id
        self.mode = mode

    async def analyze(self, perception):
        _ = perception
        return ProductAnalysis(product_name="苹果", product_type="水果", keywords=["水果"])

    async def classify(self, analysis, candidates, *, title):
        _ = analysis, candidates, title
        if self.mode == "unknown":
            return ProductClassificationDecision(
                decision="unknown", confidence=0.91, reason="无匹配", model_name="model-a"
            )
        return ProductClassificationDecision(
            decision="classified",
            level2_category_id=self.category_id,
            confidence=0.93,
            reason="水果主体明确",
            model_name="model-a",
        )

    async def review(self, analysis, candidates, *, selected_level2_id, title):
        _ = analysis, candidates, selected_level2_id, title
        if self.mode == "unknown":
            return ProductReviewDecision(
                decision="unknown", confidence=0.89, reason="无匹配", model_name="model-b"
            )
        if self.mode == "disagree":
            return ProductReviewDecision(
                decision="unknown", confidence=0.9, reason="证据不足", model_name="model-b"
            )
        return ProductReviewDecision(
            decision="classified",
            level2_category_id=self.category_id,
            confidence=0.9,
            reason="复核通过",
            model_name="model-b",
        )

    async def generate_search_terms(self, analysis, category, *, title):
        _ = analysis, category, title
        return ProductSearchTerms(core_terms=["苹果"], keyword_quality_score=0.9)

    async def suggest_category(self, analysis, *, title):
        _ = analysis, title
        return ProductCategorySuggestion(
            suggested_level2_name="候选新品类", reason="现有类目无匹配"
        )


def _pipeline(mode: str) -> S4ProductPipeline:
    taxonomy = ProductTaxonomyImporter().load(_WORKBOOK)
    child = next(item for item in taxonomy.level2 if item.category_name == "水果")
    candidate = ProductCategoryCandidate(
        category=child, fused_score=0.05, retrieval_sources=["exact", "vector"]
    )
    return S4ProductPipeline(
        _Perception(),  # type: ignore[arg-type]
        _Retriever(candidate),  # type: ignore[arg-type]
        _Inference(child.category_id, mode),  # type: ignore[arg-type]
        auto_pass_threshold=0.85,
    )


def _ctx() -> JobContext:
    return JobContext(
        job_id="job-s4",
        task_id="task-s4",
        scene="S4",
        biz_id="product-1",
        payload={"product_id": "product-1", "title": "新鲜苹果水果"},
    )


def test_agreed_high_confidence_models_auto_classify_and_publish_search_terms() -> None:
    result = asyncio.run(_pipeline("agree").run(_ctx()))

    assert result.decision == "classified"
    assert result.confidence == 0.9
    assert result.category is not None
    assert result.category.level2.name == "水果"
    assert result.search_terms is not None


def test_model_disagreement_returns_need_review_without_search_terms() -> None:
    result = asyncio.run(_pipeline("disagree").run(_ctx()))

    assert result.decision == "need_review"
    assert result.need_manual_review is True
    assert "MODEL_DISAGREEMENT" in result.reason_codes
    assert result.search_terms is None


def test_both_models_unknown_returns_unknown_and_suggestion() -> None:
    result = asyncio.run(_pipeline("unknown").run(_ctx()))

    assert result.decision == "unknown"
    assert result.category is None
    assert result.category_suggestion is not None
    assert result.search_terms is None
