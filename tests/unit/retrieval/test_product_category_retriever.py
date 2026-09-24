"""S4 二级叶子混合召回测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

from label_agent.infrastructure.taxonomy.product_taxonomy import ProductTaxonomyImporter
from label_agent.retrieval.product_category_retriever import ProductCategoryRetriever

_WORKBOOK = Path(__file__).resolve().parents[3] / "docs" / "在场电商平台商品分类信息.xlsx"


class _DeterministicEmbedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(text.count("水果")), float(text.count("手机")), 1.0] for text in texts]


def test_retrieves_only_level2_leaf_categories_and_tracks_sources() -> None:
    taxonomy = ProductTaxonomyImporter().load(_WORKBOOK)
    retriever = ProductCategoryRetriever(taxonomy, _DeterministicEmbedding(), top_k=20)

    candidates = asyncio.run(retriever.retrieve("新鲜水果 苹果 生鲜"))

    assert candidates
    assert all(item.category.level == 2 for item in candidates)
    assert candidates[0].category.category_name == "水果"
    assert "exact" in candidates[0].retrieval_sources
    assert "vector" in candidates[0].retrieval_sources
