"""真实 Kafka 联调测试；仅在显式启用时运行。"""

from __future__ import annotations

import asyncio
import json
import os
from uuid import uuid4

import pytest
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer

from label_agent.application.orchestrator import Orchestrator
from label_agent.application.process_task import ProcessTaskUseCase
from label_agent.core.context import JobContext
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.domain.models.receipt import Receipt
from label_agent.infrastructure.mq.envelope_parser import EnvelopeParser
from label_agent.infrastructure.mq.kafka_consumer import KafkaIngressConsumer
from label_agent.infrastructure.mq.kafka_publisher import KafkaPublisher
from label_agent.scenarios.registry import ScenarioRegistry

pytestmark = pytest.mark.skipif(
    os.getenv("REAL_INFRA_TEST") != "1",
    reason="设置 REAL_INFRA_TEST=1 后才运行真实基础设施联调",
)


class _FakeResult:
    def to_receipt_payload(self) -> dict:
        return {"schema_version": "1.0", "careers": [{"name": "软件工程师"}]}


class _FakeS1Handler:
    scene = "S1"

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        return envelope.v2.scene == self.scene

    async def run(self, ctx: JobContext) -> _FakeResult:
        return _FakeResult()


@pytest.mark.asyncio
async def test_real_kafka_roundtrip() -> None:
    """验证毒消息隔离、任务执行和 Kafka 回执全链路。"""
    bootstrap_servers = os.getenv("REAL_KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    suffix = uuid4().hex
    event_id = f"evt-real-{suffix}"
    task_id = f"task-real-{suffix}"
    consumer_group = f"label-agent-e2e-{suffix}"
    ingress_topic = f"agent.task.ingress.e2e.{suffix}"
    dlq_topic = f"agent.task.ingress.dlq.e2e.{suffix}"
    callback_topic = f"agent.task.callback.e2e.{suffix}"

    parser = EnvelopeParser()
    publisher = KafkaPublisher(
        bootstrap_servers=bootstrap_servers,
        callback_topic_whitelist={callback_topic},
    )
    registry = ScenarioRegistry()
    registry.register(_FakeS1Handler())
    process_task = ProcessTaskUseCase(Orchestrator(registry), publisher)
    ingress = KafkaIngressConsumer(
        bootstrap_servers=bootstrap_servers,
        topic=ingress_topic,
        dlq_topic=dlq_topic,
        consumer_group=consumer_group,
        envelope_parser=parser,
        process_task=process_task,
    )
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)
    dlq_consumer = AIOKafkaConsumer(
        dlq_topic,
        bootstrap_servers=bootstrap_servers,
        group_id=f"label-agent-e2e-dlq-{suffix}",
        auto_offset_reset="latest",
    )
    callback_consumer = AIOKafkaConsumer(
        callback_topic,
        bootstrap_servers=bootstrap_servers,
        group_id=f"label-agent-e2e-callback-{suffix}",
        auto_offset_reset="latest",
    )

    envelope = {
        "task_id": task_id,
        "task_type": "mark_tag",
        "payload_type": "certificate",
        "payload": {
            "scene": "S1",
            "biz_id": f"biz-real-{suffix}",
            "event_id": event_id,
            "text": "持有软件工程师职业资格证书。",
        },
        "priority": 2,
        "timestamp": 1720000000000,
        "callback_topic": callback_topic,
    }

    await producer.start()
    await dlq_consumer.start()
    await callback_consumer.start()
    try:
        await producer.send_and_wait(ingress_topic, b"{invalid-json")
        await producer.send_and_wait(
            ingress_topic,
            json.dumps(envelope, ensure_ascii=False).encode(),
        )
        assert await ingress.poll_once()
        assert await ingress.poll_once()

        dlq_record = await asyncio.wait_for(dlq_consumer.getone(), timeout=10)
        dlq_payload = json.loads(dlq_record.value)
        assert dlq_payload["error_type"] == "JSONDecodeError"

        callback_record = await asyncio.wait_for(callback_consumer.getone(), timeout=10)
        receipt = Receipt.model_validate_json(callback_record.value)
        assert receipt.task_id == task_id
        assert receipt.status == "success"
    finally:
        await ingress.close()
        await publisher.close()
        await producer.stop()
        await dlq_consumer.stop()
        await callback_consumer.stop()
