"""集成测试：Mock 入站直接执行并发布回执（无本地库）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from label_agent.application.orchestrator import Orchestrator
from label_agent.application.process_task import ProcessTaskUseCase
from label_agent.core.context import JobContext
from label_agent.core.exceptions import RetryableError
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.domain.models.receipt import Receipt
from label_agent.infrastructure.mq.envelope_parser import EnvelopeParser
from label_agent.infrastructure.mq.mock_consumer import MockIngressConsumer
from label_agent.infrastructure.mq.mock_publisher import MockPublisher
from label_agent.scenarios.registry import ScenarioRegistry

FIXTURE = Path(__file__).resolve().parents[3] / "configs" / "fixtures" / "mq_ingress_sample.json"


class _FakeResult:
    def to_receipt_payload(self) -> dict:
        return {"schema_version": "1.0", "careers": [{"name": "软件工程师"}]}


class _FakeS1Handler:
    scene = "S1"

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        return envelope.v2.scene == "S1"

    async def run(self, ctx: JobContext) -> _FakeResult:
        return _FakeResult()


class _FakeS2Handler:
    scene = "S2"

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        return envelope.v2.scene == "S2"

    async def run(self, ctx: JobContext) -> _FakeResult:
        return _FakeResult()


class _RetryOnceHandler:
    scene = "S1"
    calls = 0

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        return envelope.v2.scene == "S1"

    async def run(self, ctx: JobContext) -> _FakeResult:
        type(self).calls += 1
        if type(self).calls == 1:
            raise RetryableError("transient")
        return _FakeResult()


class _AlwaysRetryHandler:
    scene = "S1"

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        return envelope.v2.scene == "S1"

    async def run(self, ctx: JobContext) -> _FakeResult:
        raise RetryableError("still failing")


class _HugeResult:
    def to_receipt_payload(self) -> dict:
        return {"content": "x" * 1000}


class _HugeHandler:
    scene = "S1"

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        return envelope.v2.scene == "S1"

    async def run(self, ctx: JobContext) -> _HugeResult:
        return _HugeResult()


class _FailThenSucceedPublisher:
    def __init__(self, fail_times: int) -> None:
        self._remain = fail_times
        self.published: list[Receipt] = []

    async def publish(self, callback_topic: str, receipt: Receipt) -> None:
        if self._remain > 0:
            self._remain -= 1
            raise ConnectionError("broker unavailable")
        self.published.append(receipt)


def _process(
    registry: ScenarioRegistry,
    publisher: MockPublisher | _FailThenSucceedPublisher,
    **kwargs: object,
) -> ProcessTaskUseCase:
    return ProcessTaskUseCase(Orchestrator(registry), publisher, **kwargs)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_mock_ingress_executes_and_publishes(tmp_path: Path) -> None:
    """MockConsumer 拉取信封后直接执行并发布回执。"""
    parser = EnvelopeParser()
    receipt_dir = tmp_path / "receipts"
    publisher = MockPublisher(
        callback_topic_whitelist={"agent.task.callback"},
        receipt_dir=receipt_dir,
    )
    registry = ScenarioRegistry()
    registry.register(_FakeS1Handler())
    registry.register(_FakeS2Handler())
    consumer = MockIngressConsumer(
        envelope_parser=parser,
        process_task=_process(registry, publisher),
        fixture_path=FIXTURE,
        replay="once",
    )

    assert await consumer.poll_once() is True
    assert await consumer.poll_once() is True
    assert await consumer.poll_once() is False

    assert len(publisher.published) == 2
    assert {item.status for item in publisher.published} == {"success"}
    assert list(receipt_dir.glob("*.json"))


@pytest.mark.asyncio
async def test_retryable_error_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("label_agent.application.process_task.asyncio.sleep", _no_sleep)
    _RetryOnceHandler.calls = 0
    parser = EnvelopeParser()
    publisher = MockPublisher(callback_topic_whitelist={"agent.task.callback"}, receipt_dir=None)
    registry = ScenarioRegistry()
    registry.register(_RetryOnceHandler())
    envelope = parser.parse(
        {
            "task_id": "task-retry",
            "task_type": "mark_tag",
            "payload_type": "certificate",
            "payload": {"scene": "S1", "event_id": "evt-retry"},
            "priority": 2,
            "timestamp": 1,
            "callback_topic": "agent.task.callback",
        }
    )
    result = await _process(registry, publisher, max_attempts=3).execute(envelope)
    assert result.outcome.value == "SUCCEEDED"
    assert _RetryOnceHandler.calls == 2
    assert publisher.published[0].status == "success"


@pytest.mark.asyncio
async def test_retry_stops_at_limit_and_publishes_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_sleep(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("label_agent.application.process_task.asyncio.sleep", _no_sleep)
    parser = EnvelopeParser()
    publisher = MockPublisher(callback_topic_whitelist={"agent.task.callback"}, receipt_dir=None)
    registry = ScenarioRegistry()
    registry.register(_AlwaysRetryHandler())
    envelope = parser.parse(
        {
            "task_id": "task-dead",
            "task_type": "mark_tag",
            "payload_type": "certificate",
            "payload": {"scene": "S1"},
            "priority": 2,
            "timestamp": 1,
            "callback_topic": "agent.task.callback",
        }
    )
    result = await _process(registry, publisher, max_attempts=2).execute(envelope)
    assert result.outcome.value == "FAILED"
    assert publisher.published[0].status == "fail"
    assert publisher.published[0].payload["error_code"] == "MAX_ATTEMPTS_EXCEEDED"


@pytest.mark.asyncio
async def test_oversized_receipt_is_replaced_with_failure() -> None:
    parser = EnvelopeParser()
    publisher = MockPublisher(callback_topic_whitelist={"agent.task.callback"}, receipt_dir=None)
    registry = ScenarioRegistry()
    registry.register(_HugeHandler())
    envelope = parser.parse(
        {
            "task_id": "task-large",
            "task_type": "mark_tag",
            "payload_type": "certificate",
            "payload": {"scene": "S1"},
            "priority": 2,
            "timestamp": 1,
            "callback_topic": "agent.task.callback",
        }
    )
    result = await _process(registry, publisher, max_receipt_bytes=100).execute(envelope)
    assert result.outcome.value == "FAILED"
    assert result.published is True
    assert publisher.published[0].status == "fail"
    assert publisher.published[0].payload["error_code"] == "PAYLOAD_TOO_LARGE"


@pytest.mark.asyncio
async def test_publish_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_sleep(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("label_agent.application.process_task.asyncio.sleep", _no_sleep)
    parser = EnvelopeParser()
    publisher = _FailThenSucceedPublisher(fail_times=2)
    registry = ScenarioRegistry()
    registry.register(_FakeS1Handler())
    envelope = parser.parse(
        {
            "task_id": "task-pub",
            "task_type": "mark_tag",
            "payload_type": "certificate",
            "payload": {"scene": "S1"},
            "priority": 2,
            "timestamp": 1,
            "callback_topic": "agent.task.callback",
        }
    )
    result = await _process(registry, publisher, max_publish_attempts=3).execute(envelope)
    assert result.published is True
    assert len(publisher.published) == 1
