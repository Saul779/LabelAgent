"""ReceiptBuilder 单元测试。"""

from __future__ import annotations

from label_agent.application.receipt_builder import build_receipt
from label_agent.domain.models.envelope import EnvelopeV2Extension, ParsedEnvelope, TaskEnvelopeV1
from label_agent.domain.models.job import JobOutcome


def _envelope() -> ParsedEnvelope:
    return ParsedEnvelope(
        v1=TaskEnvelopeV1(
            task_id="t1",
            task_type="mark_tag",
            payload_type="certificate",
            payload={"scene": "S1"},
            priority=2,
            timestamp=1,
            callback_topic="agent.task.callback",
        ),
        v2=EnvelopeV2Extension(scene="S1", event_id="e1"),
    )


def test_succeeded_maps_to_success() -> None:
    receipt = build_receipt(
        envelope=_envelope(),
        outcome=JobOutcome.SUCCEEDED,
        job_id="job-1",
        started_at_ms=1000,
        result_payload={"ok": True},
    )
    assert receipt.status == "success"
    assert receipt.payload["ok"] is True


def test_need_review_includes_job_id() -> None:
    receipt = build_receipt(
        envelope=_envelope(),
        outcome=JobOutcome.NEED_REVIEW,
        job_id="job-2",
        started_at_ms=1000,
    )
    assert receipt.status == "success"
    assert receipt.message == "pending_review"
    assert receipt.payload["job_id"] == "job-2"
    assert receipt.payload["decision"] == "need_review"
    assert receipt.payload["need_manual_review"] is True


def test_s4_unknown_is_success_and_does_not_trigger_retry_semantics() -> None:
    envelope = _envelope().model_copy(
        update={
            "v1": _envelope().v1.model_copy(update={"payload_type": "product"}),
            "v2": _envelope().v2.model_copy(update={"scene": "S4"}),
        }
    )
    receipt = build_receipt(
        envelope=envelope,
        outcome=JobOutcome.SUCCEEDED,
        job_id="job-s4-unknown",
        started_at_ms=1000,
        result_payload={
            "decision": "unknown",
            "need_manual_review": True,
            "category": None,
        },
    )

    assert receipt.status == "success"
    assert receipt.payload["decision"] == "unknown"
    assert "retryable" not in receipt.payload
