"""Ingress Consumer 兼容导出：具体实现见 mock_consumer / kafka_consumer + factory。"""

from __future__ import annotations

from label_agent.infrastructure.mq.kafka_consumer import KafkaIngressConsumer as IngressConsumer

__all__ = ["IngressConsumer"]
