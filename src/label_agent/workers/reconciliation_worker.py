"""ReconciliationWorker：周期修复处于 PENDING 的标签向量。"""

from __future__ import annotations

from label_agent.core.exceptions import RetryableError
from label_agent.core.logging import get_logger
from label_agent.domain.models.tag import VectorState
from label_agent.embedding.tag_vectorizer import TagVectorizer
from label_agent.infrastructure.tag_service.client import TagServiceClient
from label_agent.workers.base_worker import BaseWorker

logger = get_logger(__name__)


class ReconciliationWorker(BaseWorker):
    """低频扫描 PENDING 标签并补偿向量化，兜底丢失的 TagCreated 事件。"""

    poll_interval_sec = 60.0

    def __init__(
        self,
        tag_service: TagServiceClient,
        tag_vectorizer: TagVectorizer,
        *,
        batch_size: int = 100,
        poll_interval_sec: float = 60.0,
    ) -> None:
        """注入标签服务、向量化器与扫描参数。"""
        super().__init__()
        self._tag_service = tag_service
        self._tag_vectorizer = tag_vectorizer
        self._batch_size = batch_size
        self.poll_interval_sec = poll_interval_sec

    async def poll_once(self) -> None:
        """补偿处理一批仍处于 PENDING 的标签。"""
        tags = await self._tag_service.list_tags_by_vector_state(
            VectorState.PENDING,
            limit=self._batch_size,
        )
        for tag in tags:
            try:
                await self._tag_vectorizer.vectorize_and_upsert(tag)
                await self._tag_service.update_vector_state(
                    tag.tag_id,
                    VectorState.READY,
                    expected_definition_version=tag.tag_definition_version,
                )
            except RetryableError:
                logger.exception(
                    "vector_reconciliation_retryable",
                    extra={"extra_fields": {"tag_id": tag.tag_id}},
                )
                continue
            except Exception:  # noqa: BLE001 - 永久失败需落状态后继续下一条
                logger.exception(
                    "vector_reconciliation_failed",
                    extra={"extra_fields": {"tag_id": tag.tag_id}},
                )
                await self._tag_service.update_vector_state(
                    tag.tag_id,
                    VectorState.FAILED,
                    expected_definition_version=tag.tag_definition_version,
                )
