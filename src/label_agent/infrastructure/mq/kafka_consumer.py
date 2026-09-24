"""KafkaIngressConsumer：执行任务并发布回执后再提交 Kafka Offset。"""

from __future__ import annotations

import json
from base64 import b64encode

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import ConsumerRecord, TopicPartition

from label_agent.application.process_task import ProcessTaskUseCase
from label_agent.core.exceptions import NonRetryableError
from label_agent.core.logging import get_logger
from label_agent.infrastructure.mq.envelope_parser import EnvelopeParser
from label_agent.workers.base_worker import BaseWorker

logger = get_logger(__name__)


class KafkaIngressConsumer(BaseWorker):
    """Kafka 入站消费者：关闭自动提交，保证处理完成（或进入 DLQ）后再 ACK。"""

    def __init__(
        self,
        bootstrap_servers: str,
        topic: str,
        dlq_topic: str,
        consumer_group: str,
        envelope_parser: EnvelopeParser,
        process_task: ProcessTaskUseCase,
    ) -> None:
        """注入 Kafka 连接、解析器与任务处理用例。"""
        super().__init__()
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._dlq_topic = dlq_topic
        self._consumer_group = consumer_group
        self._envelope_parser = envelope_parser
        self._process_task = process_task
        self._consumer: AIOKafkaConsumer | None = None
        self._dlq_producer: AIOKafkaProducer | None = None

    async def _get_consumer(self) -> AIOKafkaConsumer:
        """首次轮询时连接 Kafka。"""
        if self._consumer is None:
            consumer = AIOKafkaConsumer(
                self._topic,
                bootstrap_servers=self._bootstrap_servers,
                group_id=self._consumer_group,
                enable_auto_commit=False,
                auto_offset_reset="earliest",
            )
            await consumer.start()
            self._consumer = consumer
        return self._consumer

    async def _get_dlq_producer(self) -> AIOKafkaProducer:
        """惰性创建用于隔离毒消息的 Producer。"""
        if self._dlq_producer is None:
            producer = AIOKafkaProducer(
                bootstrap_servers=self._bootstrap_servers,
                acks="all",
                enable_idempotence=True,
            )
            await producer.start()
            self._dlq_producer = producer
        return self._dlq_producer

    async def poll_once(self) -> bool:
        """拉取一条消息，成功处理后提交 Offset；可重试失败回退 Offset。"""
        consumer = await self._get_consumer()
        batches = await consumer.getmany(timeout_ms=1000, max_records=1)
        records = [record for batch in batches.values() for record in batch]
        if not records:
            return False

        record = records[0]
        try:
            raw = json.loads(record.value.decode("utf-8"))
            envelope = self._envelope_parser.parse(raw)
            result = await self._process_task.execute(envelope)
        except (NonRetryableError, ValueError, UnicodeError) as exc:
            await self._publish_dlq(record, exc)
            await self._commit_record(consumer, record)
            logger.error(
                "kafka_ingress_dead_lettered",
                extra={
                    "extra_fields": {
                        "topic": record.topic,
                        "partition": record.partition,
                        "offset": record.offset,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                },
            )
            return True
        except Exception:
            self._seek_record(consumer, record)
            raise

        await self._commit_record(consumer, record)
        logger.info(
            "kafka_ingress_acked",
            extra={
                "extra_fields": {
                    "topic": record.topic,
                    "partition": record.partition,
                    "offset": record.offset,
                    "job_id": result.job_id,
                    "outcome": result.outcome.value,
                    "published": result.published,
                }
            },
        )
        return True

    async def _publish_dlq(self, record: ConsumerRecord, exc: Exception) -> None:
        """先可靠写入 DLQ，再由调用方提交原消息 Offset。"""
        producer = await self._get_dlq_producer()
        payload = {
            "source_topic": record.topic,
            "source_partition": record.partition,
            "source_offset": record.offset,
            "source_timestamp": record.timestamp,
            "consumer_group": self._consumer_group,
            "error_type": type(exc).__name__,
            "error": str(exc)[:2000],
            "raw_base64": b64encode(record.value).decode("ascii"),
        }
        await producer.send_and_wait(
            self._dlq_topic,
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            key=record.key,
        )

    @staticmethod
    def _seek_record(consumer: AIOKafkaConsumer, record: ConsumerRecord) -> None:
        """处理失败时回退到当前消息，供同进程下次 poll 重试。"""
        partition = TopicPartition(record.topic, record.partition)
        consumer.seek(partition, record.offset)

    @staticmethod
    async def _commit_record(
        consumer: AIOKafkaConsumer,
        record: ConsumerRecord,
    ) -> None:
        """仅提交当前消息所在分区的下一 Offset。"""
        partition = TopicPartition(record.topic, record.partition)
        await consumer.commit({partition: record.offset + 1})

    async def close(self) -> None:
        """关闭 Consumer 连接。"""
        if self._consumer is not None:
            await self._consumer.stop()
            self._consumer = None
        if self._dlq_producer is not None:
            await self._dlq_producer.stop()
            self._dlq_producer = None
