"""VectorWorker：消费 TagCreated，写入标签向量并回写向量状态。"""

from __future__ import annotations

from label_agent.core.exceptions import RetryableError
from label_agent.core.logging import get_logger
from label_agent.domain.models.tag import Tag, VectorState
from label_agent.embedding.tag_vectorizer import TagVectorizer
from label_agent.infrastructure.mq.vector_events import VectorEventConsumer
from label_agent.infrastructure.tag_service.client import TagServiceClient
from label_agent.workers.base_worker import BaseWorker

logger = get_logger(__name__)


class VectorWorker(BaseWorker):
    """向量化 Worker：消费新建标签事件，生成向量并写入 Milvus 代理，驱动标签向量状态就绪。"""

    def __init__(
        self,
        tag_service: TagServiceClient,
        tag_vectorizer: TagVectorizer,
        event_consumer: VectorEventConsumer,
        *,
        poll_interval_sec: float = 1.0,
    ) -> None:
        """注入标签服务客户端与向量化器依赖。"""
        super().__init__()
        self.poll_interval_sec = poll_interval_sec
        self._tag_service = tag_service
        self._tag_vectorizer = tag_vectorizer
        self._event_consumer = event_consumer

    async def poll_once(self) -> None:
        """消费并处理至多一条标签创建事件。"""
        received = await self._event_consumer.poll()
        if received is None:
            return
        event = received.event
        tag: Tag | None = None
        try:
            tag = await self._tag_service.get_tag(event.tag_id)
            if tag is None:
                raise RetryableError(f"TagCreated 对应标签尚不可见: {event.tag_id}")
            if tag.tag_definition_version != event.tag_definition_version:
                logger.info(
                    "vector_event_stale",
                    extra={"extra_fields": {"tag_id": tag.tag_id, "event_id": event.event_id}},
                )
                await self._event_consumer.ack(received.ack_token)
                return
            if tag.vector_state == VectorState.READY:
                await self._event_consumer.ack(received.ack_token)
                return

            await self._vectorize(tag)
            await self._event_consumer.ack(received.ack_token)
        except RetryableError:
            await self._event_consumer.nack(received.ack_token)
            raise
        except Exception as exc:  # noqa: BLE001 - 永久失败必须落状态并跳过毒消息
            try:
                await self._mark_failed(tag, event.tag_id)
            except RetryableError:
                await self._event_consumer.nack(received.ack_token)
                raise
            except Exception:  # noqa: BLE001 - 版本冲突视为该事件已过期
                logger.exception(
                    "tag_vector_failed_state_not_updated",
                    extra={"extra_fields": {"tag_id": event.tag_id}},
                )
            await self._event_consumer.ack(received.ack_token)
            logger.exception(
                "tag_vectorization_failed",
                extra={
                    "extra_fields": {
                        "tag_id": event.tag_id,
                        "event_id": event.event_id,
                        "error": str(exc),
                    }
                },
            )

    async def _vectorize(self, tag: Tag) -> None:
        """幂等写向量并以定义版本保护状态回写。"""
        await self._tag_vectorizer.vectorize_and_upsert(tag)
        await self._tag_service.update_vector_state(
            tag.tag_id,
            VectorState.READY,
            expected_definition_version=tag.tag_definition_version,
        )
        logger.info(
            "tag_vector_ready",
            extra={"extra_fields": {"tag_id": tag.tag_id}},
        )

    async def _mark_failed(self, tag: Tag | None, tag_id: str) -> None:
        """尽力回写 FAILED；回写短暂失败时让消息重新投递。"""
        if tag is None:
            return
        await self._tag_service.update_vector_state(
            tag_id,
            VectorState.FAILED,
            expected_definition_version=tag.tag_definition_version,
        )

    async def run_forever(self) -> None:
        """运行消费循环，并在退出时关闭 Kafka Consumer。"""
        try:
            await super().run_forever()
        finally:
            await self._event_consumer.close()
