"""EnvelopeParser 降级兜底逻辑（§3.1、§4.1，D006）。"""

from __future__ import annotations

from label_agent.infrastructure.mq.envelope_parser import EnvelopeParser


def _raw_message(payload: dict) -> dict:
    return {
        "task_id": "task-1",
        "task_type": "mark_tag",
        "payload_type": "dynamic",
        "payload": payload,
        "priority": 2,
        "timestamp": 1_700_000_000_000,
        "callback_topic": "agent.task.callback",
    }


def test_v1_only_message_degrades_idempotency_and_version_protection() -> None:
    parsed = EnvelopeParser().parse(_raw_message({}))
    assert parsed.degraded_idempotency is True
    assert parsed.version_protected is False
    assert parsed.effective_event_id == "task-1"


def test_v2_message_uses_event_id_and_is_version_protected() -> None:
    parsed = EnvelopeParser().parse(
        _raw_message({"event_id": "evt-1", "biz_id": "dynamic-123", "data_version": 17})
    )
    assert parsed.degraded_idempotency is False
    assert parsed.version_protected is True
    assert parsed.effective_event_id == "evt-1"
