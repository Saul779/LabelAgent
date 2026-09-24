"""内存版 VectorMatcher 单元测试。"""

from __future__ import annotations

import pytest

from label_agent.core.context import JobContext
from label_agent.domain.models.content import ContentBundle
from label_agent.retrieval.generative_domain_index import (
    DictionaryItem,
    InMemoryDomainVectorIndex,
)
from label_agent.retrieval.matchers.vector_match import VectorMatcher


class _FakeEmbedding:
    _VECTORS = {
        "摄影": [1.0, 0.0],
        "拍照": [0.9, 0.1],
        "跑步": [0.0, 1.0],
        "周末拍摄风景": [1.0, 0.0],
    }

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._VECTORS.get(text, [0.5, 0.5]) for text in texts]


def _context(*, domain: str = "content", text: str = "周末拍摄风景") -> JobContext:
    return JobContext(
        job_id="job-vector-test",
        task_id="task-vector-test",
        scene="S3",
        biz_id="biz-vector-test",
        payload={"tag_domain": domain},
        content_bundle=ContentBundle(normalized_text=text),
    )


@pytest.mark.asyncio
async def test_match_returns_deduplicated_vector_candidates() -> None:
    index = InMemoryDomainVectorIndex(
        domain="content",
        items=[
            DictionaryItem(id="tag-photography", display_name="摄影", aliases=("拍照",)),
            DictionaryItem(id="tag-running", display_name="跑步"),
        ],
        embedding_provider=_FakeEmbedding(),  # type: ignore[arg-type]
        dictionary_snapshot_version="dict-content-test",
    )
    matcher = VectorMatcher(index, top_k=3)

    result = await matcher.match(_context())

    assert [item.tag_id for item in result] == ["tag-photography", "tag-running"]
    assert result[0].match_source == "vector"
    assert result[0].match_score == pytest.approx(1.0)
    assert result[0].dictionary_snapshot_version == "dict-content-test"


@pytest.mark.asyncio
async def test_match_rejects_wrong_domain_and_empty_query() -> None:
    index = InMemoryDomainVectorIndex(
        domain="content",
        items=[DictionaryItem(id="tag-photography", display_name="摄影")],
        embedding_provider=_FakeEmbedding(),  # type: ignore[arg-type]
    )
    matcher = VectorMatcher(index)

    assert await matcher.match(_context(domain="career")) == []
    assert await matcher.match(_context(text="")) == []


def test_constructor_validates_options() -> None:
    index = InMemoryDomainVectorIndex(
        domain="content",
        items=[],
        embedding_provider=_FakeEmbedding(),  # type: ignore[arg-type]
    )

    with pytest.raises(ValueError, match="top_k"):
        VectorMatcher(index, top_k=0)
    with pytest.raises(ValueError, match="min_score"):
        VectorMatcher(index, min_score=1.1)
