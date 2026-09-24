"""KafkaPublisher：使用 aiokafka 发布回执并等待 Broker 确认。"""

from __future__ import annotations

from aiokafka import AIOKafkaProducer

from label_agent.domain.models.receipt import Receipt


class KafkaPublisher:
    """惰性创建 Kafka Producer 的回执发布器。"""

    def __init__(self, bootstrap_servers: str, callback_topic_whitelist: set[str]) -> None:
        """注入 Kafka 连接与白名单。"""
        self._bootstrap_servers = bootstrap_servers
        self._whitelist = callback_topic_whitelist
        self._producer: AIOKafkaProducer | None = None

    async def _get_producer(self) -> AIOKafkaProducer:
        """首次发布时连接 Kafka，后续复用连接。"""
        if self._producer is None:
            producer = AIOKafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                acks="all",
                enable_idempotence=True,
            )
            await producer.start()
            self._producer = producer
        return self._producer

    async def publish(self, callback_topic: str, receipt: Receipt) -> None:
        """发布 JSON 回执；仅 Broker 确认后返回。"""
        if callback_topic not in self._whitelist:
            raise ValueError(f"callback_topic 不在白名单: {callback_topic}")
        producer = await self._get_producer()
        payload = receipt.model_dump_json().encode("utf-8")
        await producer.send_and_wait(
            callback_topic,
            payload,
            key=receipt.task_id.encode("utf-8"),
        )

    async def close(self) -> None:
        """关闭 Producer 连接。"""
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None
