"""Job 四态到对外二值回执状态的映射（§3.2、§4.4，D006）。"""

from __future__ import annotations

import pytest

from label_agent.domain.models.job import JobOutcome
from label_agent.domain.models.receipt import build_message, map_outcome_to_status


@pytest.mark.parametrize(
    ("outcome", "expected_status"),
    [
        (JobOutcome.SUCCEEDED, "success"),
        (JobOutcome.NEED_REVIEW, "success"),
        (JobOutcome.PARTIAL_SUCCESS, "success"),
        (JobOutcome.FAILED, "fail"),
        (JobOutcome.SUPERSEDED, "fail"),
    ],
)
def test_map_outcome_to_status(outcome: JobOutcome, expected_status: str) -> None:
    assert map_outcome_to_status(outcome) == expected_status


def test_need_review_message_marks_pending_review() -> None:
    assert build_message(JobOutcome.NEED_REVIEW, job_id="job-1") == "pending_review"
