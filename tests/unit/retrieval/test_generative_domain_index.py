"""InMemoryDomainVectorIndex 单元测试（mock Embedding）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from label_agent.retrieval.generative_domain_index import (
    DictionaryItem,
    InMemoryDomainVectorIndex,
)

FIXTURE = Path(__file__).resolve().parents[3] / "configs" / "fixtures" / "skill_dictionary.yaml"
CERTIFICATE_FIXTURE = (
    Path(__file__).resolve().parents[3] / "configs" / "fixtures" / "certificate_dictionary.yaml"
)
CONTENT_FIXTURE = (
    Path(__file__).resolve().parents[3] / "configs" / "fixtures" / "content_dictionary.yaml"
)


class _FakeEmbedding:
    def __init__(self) -> None:
        self._cache: dict[str, list[float]] = {}

    def _vec(self, text: str) -> list[float]:
        # 用字符码构造可区分向量，同名文本同向量
        base = [float((ord(ch) % 17) + 1) for ch in text[:8]]
        while len(base) < 8:
            base.append(1.0)
        return base

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


@pytest.mark.asyncio
async def test_top1_returns_same_item_for_exact_name() -> None:
    index = InMemoryDomainVectorIndex(
        domain="skill",
        items=[
            DictionaryItem(id="skill-001", display_name="Python编程", aliases=("Python开发",)),
            DictionaryItem(id="skill-002", display_name="Java编程"),
        ],
        embedding_provider=_FakeEmbedding(),  # type: ignore[arg-type]
        dictionary_snapshot_version="dict-test",
    )
    await index.build()
    item, score = await index.top1("Python编程")
    assert item is not None
    assert item.id == "skill-001"
    assert score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_from_yaml_fixture_loads_items() -> None:
    index = InMemoryDomainVectorIndex.from_yaml(FIXTURE, _FakeEmbedding())  # type: ignore[arg-type]
    assert index.domain == "skill"
    assert len(index._items) >= 15
    await index.build()
    item, score = await index.top1("MySQL")
    assert item is not None
    assert item.display_name == "MySQL"
    assert score >= 0.0


@pytest.mark.asyncio
async def test_certificate_fixture_loads_certificate_metadata() -> None:
    index = InMemoryDomainVectorIndex.from_yaml(
        CERTIFICATE_FIXTURE,
        _FakeEmbedding(),  # type: ignore[arg-type]
    )
    assert index.domain == "certificate"
    assert len(index._items) >= 15
    pmp = next(item for item in index._items if item.id == "certificate-001")
    assert pmp.display_name == "PMP项目管理专业人士认证"
    assert pmp.resolved_metadata["organization"] == "Project Management Institute"


@pytest.mark.asyncio
async def test_from_yaml_supports_s3_tags_fixture() -> None:
    index = InMemoryDomainVectorIndex.from_yaml(
        CONTENT_FIXTURE,
        _FakeEmbedding(),  # type: ignore[arg-type]
    )

    assert index.domain == "content"
    assert index.dictionary_snapshot_version == "dict-content-2026-08-12"
    await index.build()
    item, score = await index.top1("摄影")
    assert item is not None
    assert item.id == "tag-photography"
    assert score == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_top_k_keeps_duplicate_item_hits_from_aliases() -> None:
    index = InMemoryDomainVectorIndex(
        domain="skill",
        items=[
            DictionaryItem(id="skill-001", display_name="Python", aliases=("Python开发",)),
            DictionaryItem(id="skill-002", display_name="Java"),
        ],
        embedding_provider=_FakeEmbedding(),  # type: ignore[arg-type]
    )
    await index.build()
    hits = await index.top_k("Python", k=3)
    assert len(hits) == 3
    assert [hit.item.id for hit in hits].count("skill-001") == 2


@pytest.mark.asyncio
async def test_find_exact_normalizes_whitespace() -> None:
    index = InMemoryDomainVectorIndex(
        domain="career",
        items=[
            DictionaryItem(
                id="career-001",
                display_name="Python工程师",
                aliases=("Python开发工程师",),
            ),
            DictionaryItem(
                id="career-004",
                display_name="测试工程师",
                aliases=("软件测试工程师",),
            ),
        ],
        embedding_provider=_FakeEmbedding(),  # type: ignore[arg-type]
    )
    await index.build()
    hits = index.find_exact("Python 开发工程师")
    assert len(hits) == 1
    assert hits[0].item.id == "career-001"
    assert hits[0].score == 1.0
    assert index.find_exact("软件工程师") == []
