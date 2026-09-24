"""校验 ContentLabelResult 契约约束（§3.3.1）：tags 长度 0~5、按 final_confidence 降序。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from label_agent.domain.models.s3_result import CategoryResult, ContentLabelResult, TagResult


def _build_result(tags: list[TagResult]) -> ContentLabelResult:
    return ContentLabelResult(
        biz_id="dynamic-123",
        result_revision=1,
        dictionary_snapshot_version="dict-2026-07-20",
        model_run_id="run-1",
        prompt_version="s3-v3",
        policy_version="provisional-rule-mvp-1",
        primary_category=CategoryResult(category_id="cat-photo", name="摄影", confidence=0.9),
        tags=tags,
    )


def _tag(final_confidence: float) -> TagResult:
    return TagResult(
        tag_id="tag-19",
        canonical_tag_id="tag-19",
        display_name="复古胶片风",
        name_type="standard",
        source="matched",
        model_score=0.86,
        final_confidence=final_confidence,
        vector_state="READY",
    )


def test_tags_must_be_sorted_by_final_confidence_desc() -> None:
    with pytest.raises(ValidationError):
        _build_result([_tag(0.5), _tag(0.9)])


def test_tags_length_must_not_exceed_five() -> None:
    with pytest.raises(ValidationError):
        _build_result([_tag(0.9 - i * 0.1) for i in range(6)])


def test_valid_result_passes() -> None:
    result = _build_result([_tag(0.9), _tag(0.5)])
    assert len(result.tags) == 2
