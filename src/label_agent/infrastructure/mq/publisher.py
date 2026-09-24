"""Publisher 兼容导出：优先使用 protocols.MqPublisher + factory.create_publisher。

历史 `MqPublisher` 类名保留为 Kafka 占位的别名，避免旧 import 断裂。
"""

from __future__ import annotations

from label_agent.infrastructure.mq.kafka_publisher import KafkaPublisher as MqPublisher

__all__ = ["MqPublisher"]
