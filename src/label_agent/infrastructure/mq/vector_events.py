"""标签向量化事件消费端口及 Kafka 实现。"""

from __future__ import annotations

import json
from typing import Protocol

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import TopicPartition
from pydantic import ValidationError

from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.vector_event import (
    ReceivedTagCreatedEvent,
    TagCreatedEvent,
)


class VectorEventConsumer(Protocol):
    """支持显式确认和回退游标的标签创建事件消费端口。"""

    async def poll(self) -> ReceivedTagCreatedEvent | None: ...

    async def ack(self, ack_token: str) -> None: ...

    async def nack(self, ack_token: str) -> None: ...

    async def close(self) -> None: ...


class KafkaVectorEventConsumer:
    """手动提交 Offset 的 Kafka 标签创建事件消费者。"""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topic: str,
        consumer_group: str,
        poll_timeout_ms: int = 1000,
    ) -> None:
        self._topic = topic
        self._poll_timeout_ms = poll_timeout_ms
        self._consumer = AIOKafkaConsumer(
            topic,
            bootstrap_servers=bootstrap_servers,
            group_id=consumer_group,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        self._started = False
        self._positions: dict[str, tuple[TopicPartition, int]] = {}

    async def poll(self) -> ReceivedTagCreatedEvent | None:
        """拉取至多一条事件；无消息时返回 None。"""
        if not self._started:
            await self._consumer.start()
            self._started = True
        batches = await self._consumer.getmany(
            timeout_ms=self._poll_timeout_ms,
            max_records=1,
        )
        for topic_partition, messages in batches.items():
            if not messages:
                continue
            message = messages[0]
            token = f"{topic_partition.topic}:{topic_partition.partition}:{message.offset}"
            self._positions[token] = (topic_partition, message.offset)
            try:
                raw = json.loads(message.value.decode("utf-8"))
                event = TagCreatedEvent.model_validate(raw)
            except (
                AttributeError,
                TypeError,
                UnicodeDecodeError,
                json.JSONDecodeError,
                ValidationError,
            ) as exc:
                await self.ack(token)
                raise NonRetryableError(f"TagCreated 事件结构不合法: {exc}") from exc
            return ReceivedTagCreatedEvent(event=event, ack_token=token)
        return None

    async def ack(self, ack_token: str) -> None:
        """处理成功后提交下一条 Offset。"""
        position = self._positions.pop(ack_token, None)
        if position is None:
            return
        topic_partition, offset = position
        await self._consumer.commit({topic_partition: offset + 1})

    async def nack(self, ack_token: str) -> None:
        """处理失败时回退到当前 Offset，允许下轮重试。"""
        position = self._positions.pop(ack_token, None)
        if position is None:
            return
        topic_partition, offset = position
        self._consumer.seek(topic_partition, offset)

    async def close(self) -> None:
        """停止 Kafka Consumer，释放连接并触发组内再均衡。"""
        if self._started:
            await self._consumer.stop()
            self._started = False
