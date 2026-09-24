"""复用通用 Embedding/Milvus 基础设施的 S4 远程类目向量召回。"""

from __future__ import annotations

from typing import Any

from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.s4_product import (
    ProductCategoryCandidate,
    ProductCategoryRecord,
)
from label_agent.inference.embeddings.base import EmbeddingProvider
from label_agent.infrastructure.milvus_proxy.client import MilvusProxyClient


class ProductCategoryVectorRetriever:
    """从服务端类目向量集合召回二级叶子，并还原分类所需元数据。"""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        milvus_proxy: MilvusProxyClient,
        *,
        collection: str,
        taxonomy_version: str,
        top_k: int = 20,
    ) -> None:
        if not collection.strip():
            raise ValueError("S4 类目向量 collection 不能为空")
        if not taxonomy_version.strip():
            raise ValueError("S4 远程向量召回必须配置 taxonomy_version")
        if top_k <= 0:
            raise ValueError("S4 类目向量 top_k 必须大于 0")
        self._embedding_provider = embedding_provider
        self._milvus_proxy = milvus_proxy
        self._collection = collection
        self._taxonomy_version = taxonomy_version
        self._top_k = top_k

    @property
    def taxonomy_version(self) -> str:
        """返回本次检索固定使用的类目版本。"""
        return self._taxonomy_version

    async def retrieve(self, query_text: str) -> list[ProductCategoryCandidate]:
        """生成查询向量并调用 Milvus 代理召回服务端类目。"""
        query = query_text.strip()
        if not query:
            return []
        vectors = await self._embedding_provider.embed([query])
        if len(vectors) != 1 or not vectors[0]:
            raise NonRetryableError("S4 类目检索未获得有效查询向量")

        hits = await self._milvus_proxy.search(
            self._collection,
            vectors[0],
            self._top_k,
            {
                "level": 2,
                "status": "active",
                "taxonomy_version": self._taxonomy_version,
            },
        )
        candidates: dict[str, ProductCategoryCandidate] = {}
        for hit in hits:
            candidate = self._to_candidate(hit)
            current = candidates.get(candidate.category.category_id)
            if current is None or candidate.fused_score > current.fused_score:
                candidates[candidate.category.category_id] = candidate
        return sorted(
            candidates.values(),
            key=lambda item: item.fused_score,
            reverse=True,
        )[: self._top_k]

    def _to_candidate(self, hit: dict[str, Any]) -> ProductCategoryCandidate:
        metadata = hit.get("metadata")
        if not isinstance(metadata, dict):
            raise NonRetryableError("S4 类目向量命中缺少 metadata 对象")

        category_id = str(metadata.get("category_id") or hit.get("id") or "").strip()
        payload = {
            "category_id": category_id,
            "category_name": metadata.get("category_name"),
            "level": metadata.get("level"),
            "parent_category_id": metadata.get("parent_category_id"),
            "parent_category_name": metadata.get("parent_category_name"),
            "taxonomy_version": metadata.get("taxonomy_version"),
            "status": metadata.get("status", "active"),
            "category_description": metadata.get("category_description", ""),
            "aliases": metadata.get("aliases", []),
            "include_products": metadata.get("include_products", []),
            "exclude_products": metadata.get("exclude_products", []),
            "positive_keywords": metadata.get("positive_keywords", []),
            "negative_keywords": metadata.get("negative_keywords", []),
            "classification_rules": metadata.get("classification_rules", []),
        }
        try:
            category = ProductCategoryRecord.model_validate(payload)
            raw_score = hit.get("score")
            if not isinstance(raw_score, int | float | str):
                raise ValueError("score 必须是数值")
            score = float(raw_score)
            candidate = ProductCategoryCandidate(
                category=category,
                fused_score=score,
                retrieval_sources=["vector"],
            )
        except (TypeError, ValueError) as exc:
            raise NonRetryableError(f"S4 类目向量命中格式非法: {exc}") from exc

        if category.level != 2:
            raise NonRetryableError(f"S4 类目向量命中不是二级叶子: {category.category_id}")
        if category.taxonomy_version != self._taxonomy_version:
            raise NonRetryableError(
                "S4 类目向量命中版本不一致: "
                f"expected={self._taxonomy_version} actual={category.taxonomy_version}"
            )
        if not category.parent_category_id or not category.parent_category_name:
            raise NonRetryableError(f"S4 类目向量命中缺少父类目元数据: {category.category_id}")
        return candidate
