"""S4 最终结果契约不变量测试。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from label_agent.domain.models.s4_result import ProductLabelResult, ProductModelRun


def _runs() -> dict:
    return {
        "classifier": ProductModelRun(
            model_name="model-a",
            model_alias="primary",
            prompt_version="s4-classify-v1",
            confidence=0.9,
            decision="unknown",
        ),
        "reviewer": ProductModelRun(
            model_name="model-b",
            model_alias="reviewer",
            prompt_version="s4-review-v1",
            confidence=0.88,
            decision="unknown",
        ),
    }


def test_unknown_is_successful_business_result_without_category() -> None:
    result = ProductLabelResult(
        product_id="p1",
        taxonomy_version="v1",
        confidence=0.88,
        decision="unknown",
        need_manual_review=True,
        model_runs=_runs(),
    )

    assert result.to_receipt_payload()["decision"] == "unknown"
    assert result.category is None


def test_unknown_rejects_search_terms_or_formal_category() -> None:
    with pytest.raises(ValidationError):
        ProductLabelResult(
            product_id="p1",
            taxonomy_version="v1",
            confidence=0.88,
            decision="unknown",
            need_manual_review=False,
            model_runs=_runs(),
        )
