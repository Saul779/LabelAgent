"""标签向量异步 Worker 与补偿对账测试。"""

from __future__ import annotations

from collections import deque

import pytest

from label_agent.core.exceptions import RetryableError
from label_agent.domain.models.tag import LifecycleStatus, Tag, VectorState
from label_agent.domain.models.vector_event import ReceivedTagCreatedEvent, TagCreatedEvent
from label_agent.embedding.tag_vectorizer import TagVectorizer
from label_agent.infrastructure.tag_service.mock_client import MockTagServiceClient
from label_agent.workers.reconciliation_worker import ReconciliationWorker
from label_agent.workers.vector_worker import VectorWorker


class _Embedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[1.0, float(len(text))] for text in texts]


class _MilvusProxy:
    def __init__(self) -> None:
        self.upserts: list[tuple] = []

    async def upsert(self, collection, ids, vectors, metadata) -> None:
        self.upserts.append((collection, ids, vectors, metadata))


class _UnavailableMilvusProxy:
    async def upsert(self, collection, ids, vectors, metadata) -> None:
        raise RetryableError("Milvus 暂时不可用")


class _EventConsumer:
    def __init__(self, events: list[ReceivedTagCreatedEvent]) -> None:
        self._events = deque(events)
        self.acked: list[str] = []
        self.nacked: list[str] = []

    async def poll(self) -> ReceivedTagCreatedEvent | None:
        return self._events.popleft() if self._events else None

    async def ack(self, ack_token: str) -> None:
        self.acked.append(ack_token)

    async def nack(self, ack_token: str) -> None:
        self.nacked.append(ack_token)

    async def close(self) -> None:
        return None


def _tag() -> Tag:
    return Tag(
        tag_id="tag-1",
        canonical_tag_id="tag-1",
        display_name="清晨观云",
        name_type="standard",
        domain="content",
        lifecycle_status=LifecycleStatus.ACTIVE,
        vector_state=VectorState.PENDING,
        tag_definition_version=2,
        embedding_space_id="text-v1",
    )


def _received() -> ReceivedTagCreatedEvent:
    return ReceivedTagCreatedEvent(
        event=TagCreatedEvent(
            event_id="evt-1",
            tag_id="tag-1",
            tag_definition_version=2,
            embedding_space_id="text-v1",
        ),
        ack_token="topic:0:1",
    )


@pytest.mark.asyncio
async def test_vector_worker_upserts_then_marks_ready_and_acks() -> None:
    tag_service = MockTagServiceClient()
    tag_service._tags["tag-1"] = _tag()
    proxy = _MilvusProxy()
    consumer = _EventConsumer([_received()])
    worker = VectorWorker(
        tag_service,
        TagVectorizer(_Embedding(), proxy),  # type: ignore[arg-type]
        consumer,
    )

    await worker.poll_once()

    updated = await tag_service.get_tag("tag-1")
    assert updated is not None
    assert updated.vector_state == VectorState.READY
    assert consumer.acked == ["topic:0:1"]
    assert consumer.nacked == []
    assert proxy.upserts[0][1] == ["tag-1:2:text-v1"]


@pytest.mark.asyncio
async def test_vector_worker_acks_stale_event_without_upsert() -> None:
    tag_service = MockTagServiceClient()
    tag_service._tags["tag-1"] = _tag().model_copy(update={"tag_definition_version": 3})
    proxy = _MilvusProxy()
    consumer = _EventConsumer([_received()])
    worker = VectorWorker(
        tag_service,
        TagVectorizer(_Embedding(), proxy),  # type: ignore[arg-type]
        consumer,
    )

    await worker.poll_once()

    assert consumer.acked == ["topic:0:1"]
    assert proxy.upserts == []


@pytest.mark.asyncio
async def test_vector_worker_nacks_retryable_failure() -> None:
    tag_service = MockTagServiceClient()
    tag_service._tags["tag-1"] = _tag()
    consumer = _EventConsumer([_received()])
    worker = VectorWorker(
        tag_service,
        TagVectorizer(_Embedding(), _UnavailableMilvusProxy()),  # type: ignore[arg-type]
        consumer,
    )

    with pytest.raises(RetryableError):
        await worker.poll_once()

    assert consumer.acked == []
    assert consumer.nacked == ["topic:0:1"]


@pytest.mark.asyncio
async def test_reconciliation_worker_repairs_pending_tag() -> None:
    tag_service = MockTagServiceClient()
    tag_service._tags["tag-1"] = _tag()
    proxy = _MilvusProxy()
    worker = ReconciliationWorker(
        tag_service,
        TagVectorizer(_Embedding(), proxy),  # type: ignore[arg-type]
    )

    await worker.poll_once()

    updated = await tag_service.get_tag("tag-1")
    assert updated is not None
    assert updated.vector_state == VectorState.READY
    assert len(proxy.upserts) == 1
