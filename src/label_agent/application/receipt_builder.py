"""ReceiptBuilder：Job 终态 → 对外回执（§3.2）。"""

from __future__ import annotations

from typing import Any

from label_agent.core.timeutil import now_ms
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.domain.models.job import JobOutcome
from label_agent.domain.models.receipt import Receipt, build_message, map_outcome_to_status


def build_receipt(
    *,
    envelope: ParsedEnvelope,
    outcome: JobOutcome,
    job_id: str,
    started_at_ms: int,
    result_payload: dict[str, Any] | None = None,
) -> Receipt:
    """按 outcome 组装回执；外层 status 与 payload 业务决策正交。"""
    status = map_outcome_to_status(outcome)
    message = build_message(outcome, job_id)
    payload: dict[str, Any] = dict(result_payload or {})
    if outcome in {JobOutcome.NEED_REVIEW, JobOutcome.PARTIAL_SUCCESS}:
        payload.setdefault("job_id", job_id)
    if outcome is JobOutcome.NEED_REVIEW:
        payload.setdefault("decision", "need_review")
        payload.setdefault("need_manual_review", True)
    if outcome is JobOutcome.FAILED:
        payload.setdefault("retryable", False)

    finished = now_ms()
    return Receipt(
        task_id=envelope.v1.task_id,
        task_type=envelope.v1.task_type,
        payload_type=envelope.v1.payload_type,
        status=status,
        message=message,
        payload=payload,
        process_time=max(0, finished - started_at_ms),
        timestamp=finished,
    )
