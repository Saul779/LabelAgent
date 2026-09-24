"""Kafka 入站毒消息隔离测试。"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from label_agent.infrastructure.mq.envelope_parser import EnvelopeParser
from label_agent.infrastructure.mq.kafka_consumer import KafkaIngressConsumer


class _FakeConsumer:
    def __init__(self, record: SimpleNamespace) -> None:
        self._record = record
        self.committed: dict | None = None
        self.seeked: tuple | None = None

    async def getmany(self, **kwargs) -> dict:
        return {object(): [self._record]}

    async def commit(self, offsets: dict) -> None:
        self.committed = offsets

    def seek(self, partition: object, offset: int) -> None:
        self.seeked = (partition, offset)


class _FakeProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, bytes, bytes | None]] = []

    async def send_and_wait(
        self,
        topic: str,
        value: bytes,
        *,
        key: bytes | None,
    ) -> None:
        self.sent.append((topic, value, key))


class _UnusedProcessTask:
    async def execute(self, envelope) -> None:  # noqa: ANN001
        raise AssertionError("毒消息不应进入 ProcessTask")


class _RetryableProcessTask:
    async def execute(self, envelope) -> None:  # noqa: ANN001
        raise RuntimeError("broker temporarily unavailable")


@pytest.mark.asyncio
async def test_invalid_json_is_dead_lettered_before_offset_commit() -> None:
    record = SimpleNamespace(
        topic="agent.task.ingress",
        partition=2,
        offset=17,
        timestamp=123,
        value=b"{invalid-json",
        key=b"task-key",
    )
    kafka = _FakeConsumer(record)
    dlq = _FakeProducer()
    consumer = KafkaIngressConsumer(
        bootstrap_servers="kafka:9092",
        topic="agent.task.ingress",
        dlq_topic="agent.task.ingress.dlq",
        consumer_group="label-agent",
        envelope_parser=EnvelopeParser(),
        process_task=_UnusedProcessTask(),
    )
    consumer._consumer = kafka
    consumer._dlq_producer = dlq

    consumed = await consumer.poll_once()

    assert consumed is True
    assert dlq.sent[0][0] == "agent.task.ingress.dlq"
    assert kafka.committed is not None
    assert list(kafka.committed.values()) == [18]


@pytest.mark.asyncio
async def test_unclassified_runtime_error_seeks_back_and_keeps_offset_uncommitted() -> None:
    raw = {
        "task_id": "task-1",
        "task_type": "mark_tag",
        "payload_type": "certificate",
        "payload": {"scene": "S1"},
        "priority": 2,
        "timestamp": 1,
        "callback_topic": "agent.task.callback",
    }
    record = SimpleNamespace(
        topic="agent.task.ingress",
        partition=0,
        offset=3,
        timestamp=123,
        value=json.dumps(raw).encode("utf-8"),
        key=None,
    )
    kafka = _FakeConsumer(record)
    dlq = _FakeProducer()
    consumer = KafkaIngressConsumer(
        bootstrap_servers="kafka:9092",
        topic="agent.task.ingress",
        dlq_topic="agent.task.ingress.dlq",
        consumer_group="label-agent",
        envelope_parser=EnvelopeParser(),
        process_task=_RetryableProcessTask(),
    )
    consumer._consumer = kafka
    consumer._dlq_producer = dlq

    with pytest.raises(RuntimeError, match="temporarily unavailable"):
        await consumer.poll_once()

    assert kafka.committed is None
    assert kafka.seeked is not None
    assert kafka.seeked[1] == 3
    assert dlq.sent == []
