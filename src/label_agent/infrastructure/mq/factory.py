"""按配置创建 MQ 入站/出站实现（mock | kafka）。"""

from __future__ import annotations

from pathlib import Path

from label_agent.application.process_task import ProcessTaskUseCase
from label_agent.infrastructure.mq.envelope_parser import EnvelopeParser
from label_agent.infrastructure.mq.kafka_consumer import KafkaIngressConsumer
from label_agent.infrastructure.mq.kafka_publisher import KafkaPublisher
from label_agent.infrastructure.mq.mock_consumer import MockIngressConsumer
from label_agent.infrastructure.mq.mock_publisher import MockPublisher
from label_agent.infrastructure.mq.protocols import MqIngressConsumer, MqPublisher
from label_agent.settings import Settings


def parse_callback_whitelist(raw: str) -> set[str]:
    """解析逗号分隔的 callback_topic 白名单。"""
    return {item.strip() for item in raw.split(",") if item.strip()}


def _resolve_backend(settings: Settings) -> str:
    """环境变量 MQ_BACKEND 优先，否则读 yaml mq.backend。"""
    return settings.effective_mq_backend


def create_publisher(settings: Settings) -> MqPublisher:
    """按 mq.backend 创建出站 Publisher。"""
    whitelist = parse_callback_whitelist(settings.mq_callback_topic_whitelist)
    backend = _resolve_backend(settings)
    if backend == "mock":
        return MockPublisher(
            callback_topic_whitelist=whitelist,
            receipt_dir=settings.mq_mock_receipt_dir,
        )
    if backend == "kafka":
        return KafkaPublisher(
            bootstrap_servers=settings.mq_bootstrap_servers,
            callback_topic_whitelist=whitelist,
        )
    raise ValueError(f"不支持的 mq.backend: {backend}")


def create_ingress_consumer(
    settings: Settings,
    *,
    envelope_parser: EnvelopeParser,
    process_task: ProcessTaskUseCase,
) -> MqIngressConsumer:
    """按 mq.backend 创建入站 Consumer。"""
    backend = _resolve_backend(settings)
    yaml_mq = settings.yaml_config.get("mq") or {}
    mock_cfg = yaml_mq.get("mock") or {}
    if backend == "mock":
        fixture = settings.mq_mock_ingress_fixture or mock_cfg.get(
            "ingress_fixture", "configs/fixtures/mq_ingress_sample.json"
        )
        replay = settings.mq_mock_replay or str(mock_cfg.get("replay", "once"))
        interval = float(yaml_mq.get("poll_interval_sec") or 1.0)
        return MockIngressConsumer(
            envelope_parser=envelope_parser,
            process_task=process_task,
            fixture_path=Path(fixture),
            replay=replay,
            poll_interval_sec=interval,
        )
    if backend == "kafka":
        return KafkaIngressConsumer(
            bootstrap_servers=settings.mq_bootstrap_servers,
            topic=settings.mq_ingress_topic,
            dlq_topic=settings.mq_ingress_dlq_topic,
            consumer_group=settings.mq_consumer_group,
            envelope_parser=envelope_parser,
            process_task=process_task,
        )
    raise ValueError(f"不支持的 mq.backend: {backend}")
