"""S4 服务端类目向量召回适配器测试。"""

from __future__ import annotations

import pytest

from label_agent.core.exceptions import NonRetryableError
from label_agent.retrieval.product_category_vector_retriever import (
    ProductCategoryVectorRetriever,
)


class _Embedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        assert texts == ["新鲜苹果"]
        return [[1.0, 0.0]]


class _MilvusProxy:
    def __init__(self, hits: list[dict]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, list[float], int, dict]] = []

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict,
    ) -> list[dict]:
        self.calls.append((collection, query_vector, top_k, filters))
        return self.hits


def _hit(*, score: float = 0.91, version: str = "taxonomy-v1") -> dict:
    return {
        "id": "category-fruit",
        "score": score,
        "metadata": {
            "category_id": "category-fruit",
            "category_name": "水果",
            "level": 2,
            "parent_category_id": "category-food",
            "parent_category_name": "食品生鲜",
            "taxonomy_version": version,
            "status": "active",
            "category_description": "供直接食用的新鲜水果",
            "aliases": ["鲜果"],
            "include_products": ["苹果"],
            "exclude_products": ["水果刀"],
            "positive_keywords": ["苹果"],
            "negative_keywords": ["水果刀"],
            "classification_rules": ["主体必须是可食用水果"],
        },
    }


@pytest.mark.asyncio
async def test_reuses_embedding_and_milvus_proxy_to_retrieve_categories() -> None:
    proxy = _MilvusProxy([_hit()])
    retriever = ProductCategoryVectorRetriever(
        _Embedding(),  # type: ignore[arg-type]
        proxy,  # type: ignore[arg-type]
        collection="product_category_vectors",
        taxonomy_version="taxonomy-v1",
        top_k=20,
    )

    candidates = await retriever.retrieve("新鲜苹果")

    assert candidates[0].category.category_name == "水果"
    assert candidates[0].category.parent_category_name == "食品生鲜"
    assert candidates[0].retrieval_sources == ["vector"]
    assert proxy.calls == [
        (
            "product_category_vectors",
            [1.0, 0.0],
            20,
            {"level": 2, "status": "active", "taxonomy_version": "taxonomy-v1"},
        )
    ]


@pytest.mark.asyncio
async def test_rejects_hit_from_another_taxonomy_version() -> None:
    retriever = ProductCategoryVectorRetriever(
        _Embedding(),  # type: ignore[arg-type]
        _MilvusProxy([_hit(version="taxonomy-v2")]),  # type: ignore[arg-type]
        collection="product_category_vectors",
        taxonomy_version="taxonomy-v1",
    )

    with pytest.raises(NonRetryableError, match="版本不一致"):
        await retriever.retrieve("新鲜苹果")


@pytest.mark.asyncio
async def test_rejects_hit_without_parent_metadata() -> None:
    hit = _hit()
    del hit["metadata"]["parent_category_id"]
    retriever = ProductCategoryVectorRetriever(
        _Embedding(),  # type: ignore[arg-type]
        _MilvusProxy([hit]),  # type: ignore[arg-type]
        collection="product_category_vectors",
        taxonomy_version="taxonomy-v1",
    )

    with pytest.raises(NonRetryableError, match="缺少父类目元数据"):
        await retriever.retrieve("新鲜苹果")
