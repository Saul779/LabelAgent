"""T1 1.0 严格结果契约与内部 Job 状态映射。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from label_agent.domain.models.job import JobOutcome
from label_agent.domain.models.t1_result import TaskDetailExtractionError, TaskDetailResult


def _error(code: str) -> TaskDetailExtractionError:
    return TaskDetailExtractionError(
        code=code,
        field="service_mode",
        message="test",
        retryable=False,
    )


def test_t1_result_serializes_strict_schema_1_0() -> None:
    result = TaskDetailResult(
        accept_mode="public",
        biz_task_type="skill",
        required_skills=["电脑维修"],
        service_mode="offline",
    )

    assert result.to_receipt_payload() == {
        "schema_version": "1.0",
        "accept_mode": "public",
        "biz_task_type": "skill",
        "relation_target": None,
        "relation_target_detail": None,
        "required_skills": ["电脑维修"],
        "service_mode": "offline",
        "extraction_errors": [],
    }
    assert result.to_job_outcome() is JobOutcome.SUCCEEDED


def test_t1_result_maps_warning_and_ambiguity_to_job_outcomes() -> None:
    partial = TaskDetailResult(
        accept_mode="public",
        biz_task_type="dessert",
        extraction_errors=[_error("MISSING_EXPLICIT_SERVICE_MODE")],
    )
    review = TaskDetailResult(
        accept_mode="public",
        biz_task_type="dessert",
        extraction_errors=[_error("AMBIGUOUS_SERVICE_MODE")],
    )

    assert partial.to_job_outcome() is JobOutcome.PARTIAL_SUCCESS
    assert review.to_job_outcome() is JobOutcome.NEED_REVIEW


def test_t1_result_forbids_unreviewed_extra_fields() -> None:
    with pytest.raises(ValidationError):
        TaskDetailResult.model_validate(
            {
                "accept_mode": "public",
                "biz_task_type": "dessert",
                "extended_fields": {"unexpected": True},
            }
        )


@pytest.mark.parametrize("value", ["open", "", None, "PUBLIC"])
def test_t1_result_rejects_invalid_accept_mode(value) -> None:
    with pytest.raises(ValidationError):
        TaskDetailResult.model_validate(
            {
                "accept_mode": value,
                "biz_task_type": "dessert",
            }
        )
