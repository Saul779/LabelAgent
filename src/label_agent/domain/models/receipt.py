"""回执契约（v1，已确认，实现唯一对外契约，§3.2）与 Job 四态映射（D006、§4.4）。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from label_agent.domain.models.job import JobOutcome


class Receipt(BaseModel):
    """处理回执：向下游确认 Job 结果的标准消息载体。"""

    task_id: str
    task_type: str
    payload_type: str
    status: str  # 仅 "success" / "fail"
    message: str = ""
    payload: dict[str, Any] = {}
    process_time: int
    timestamp: int


_MESSAGE_BY_OUTCOME: dict[JobOutcome, str] = {
    JobOutcome.SUCCEEDED: "",
    JobOutcome.NEED_REVIEW: "pending_review",
    JobOutcome.PARTIAL_SUCCESS: "partial_success",
    JobOutcome.FAILED: "failed",
    JobOutcome.SUPERSEDED: "superseded",
}


def map_outcome_to_status(outcome: JobOutcome) -> str:
    """外层 status 只表达技术处理是否完成，不表达业务是否自动通过。

    NEED_REVIEW/PARTIAL_SUCCESS 已产出可消费的业务结果，因此映射 success；真正未能
    产出有效结果的 FAILED/SUPERSEDED 才映射 fail。S4 的 unknown/need_review 正常走
    SUCCEEDED，并由 payload.decision 表达。
    """
    return (
        "success"
        if outcome in {JobOutcome.SUCCEEDED, JobOutcome.NEED_REVIEW, JobOutcome.PARTIAL_SUCCESS}
        else "fail"
    )


def build_message(outcome: JobOutcome, job_id: str) -> str:
    """按 Job 终态映射回执可读 message 文案。"""
    return _MESSAGE_BY_OUTCOME.get(outcome, "failed")
