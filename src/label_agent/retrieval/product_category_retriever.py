"""S4 二级叶子类目的 exact/alias/BM25/vector 混合召回与 RRF 融合。"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from typing import Protocol

from label_agent.domain.models.s4_product import (
    ProductCategoryCandidate,
)
from label_agent.inference.embeddings.base import EmbeddingProvider
from label_agent.infrastructure.taxonomy.product_taxonomy import ProductTaxonomy


class ProductCategorySearch(Protocol):
    """S4 类目召回统一协议，本地索引与远程向量库均可实现。"""

    @property
    def taxonomy_version(self) -> str:
        """返回当前召回使用的类目版本。"""
        ...

    async def retrieve(self, query_text: str) -> list[ProductCategoryCandidate]:
        """按商品查询文本召回二级叶子类目。"""
        ...


class ProductCategoryRetriever:
    """只检索 L2 叶子类目；L1 必须由 parent_category_id 确定。"""

    def __init__(
        self,
        taxonomy: ProductTaxonomy,
        embedding_provider: EmbeddingProvider,
        *,
        top_k: int = 20,
        rrf_k: int = 60,
    ) -> None:
        self._taxonomy = taxonomy
        self._embedding_provider = embedding_provider
        self._top_k = top_k
        self._rrf_k = rrf_k
        self._records = list(taxonomy.level2)
        self._vectors: list[list[float]] = []
        self._documents = [_terms(item.index_text) for item in self._records]

    @property
    def taxonomy_version(self) -> str:
        """返回内存类目快照版本。"""
        return self._taxonomy.version

    async def build(self) -> None:
        """为每个二级叶子类目构建向量；允许启动阶段显式预热。"""
        if self._vectors:
            return
        self._vectors = await self._embedding_provider.embed(
            [record.index_text for record in self._records]
        )
        if len(self._vectors) != len(self._records):
            raise RuntimeError("商品类目向量数量与二级类目数量不一致")

    async def retrieve(self, query_text: str) -> list[ProductCategoryCandidate]:
        query = (query_text or "").strip()
        if not query:
            return []
        if not self._vectors:
            await self.build()

        rankings = {
            "exact": self._exact_rank(query),
            "alias": self._alias_rank(query),
            "bm25": self._bm25_rank(query),
            "vector": await self._vector_rank(query),
        }
        scores: dict[str, float] = defaultdict(float)
        sources: dict[str, list[str]] = defaultdict(list)
        by_id = {record.category_id: record for record in self._records}
        for source, ranked in rankings.items():
            for rank, category_id in enumerate(ranked, start=1):
                scores[category_id] += 1.0 / (self._rrf_k + rank)
                sources[category_id].append(source)
        ordered = sorted(scores, key=lambda category_id: scores[category_id], reverse=True)
        return [
            ProductCategoryCandidate(
                category=by_id[category_id],
                fused_score=scores[category_id],
                retrieval_sources=sources[category_id],
            )
            for category_id in ordered[: self._top_k]
        ]

    def _exact_rank(self, query: str) -> list[str]:
        compact = _compact(query)
        matches = [
            record
            for record in self._records
            if _compact(record.category_name) in compact or _compact(record.path) in compact
        ]
        matches.sort(key=lambda record: len(record.category_name), reverse=True)
        return [record.category_id for record in matches]

    def _alias_rank(self, query: str) -> list[str]:
        compact = _compact(query)
        scored: list[tuple[int, str]] = []
        for record in self._records:
            hits = [alias for alias in record.aliases if _compact(alias) in compact]
            if hits:
                scored.append((max(len(alias) for alias in hits), record.category_id))
        scored.sort(reverse=True)
        return [category_id for _, category_id in scored]

    def _bm25_rank(self, query: str) -> list[str]:
        query_terms = _terms(query)
        if not query_terms:
            return []
        document_count = len(self._documents)
        avg_length = sum(len(document) for document in self._documents) / max(1, document_count)
        document_frequency: Counter[str] = Counter()
        for document in self._documents:
            document_frequency.update(set(document))

        scored: list[tuple[float, str]] = []
        for record, document in zip(self._records, self._documents, strict=True):
            frequencies = Counter(document)
            score = 0.0
            for term in query_terms:
                frequency = frequencies.get(term, 0)
                if not frequency:
                    continue
                df = document_frequency[term]
                inverse_frequency = math.log(1.0 + (document_count - df + 0.5) / (df + 0.5))
                denominator = frequency + 1.5 * (
                    1.0 - 0.75 + 0.75 * len(document) / max(1.0, avg_length)
                )
                score += inverse_frequency * frequency * 2.5 / denominator
            if score > 0:
                scored.append((score, record.category_id))
        scored.sort(reverse=True)
        return [category_id for _, category_id in scored[: max(self._top_k * 3, 50)]]

    async def _vector_rank(self, query: str) -> list[str]:
        query_vectors = await self._embedding_provider.embed([query])
        if not query_vectors:
            return []
        scored = [
            (_cosine(query_vectors[0], vector), record.category_id)
            for record, vector in zip(self._records, self._vectors, strict=True)
        ]
        scored.sort(reverse=True)
        return [category_id for _, category_id in scored[: max(self._top_k * 3, 50)]]


def _compact(text: str) -> str:
    return "".join(char.lower() for char in text if not char.isspace() and char not in "/>-_")


def _terms(text: str) -> list[str]:
    """中英文均可用的轻量分词：连续 ASCII token + 汉字 unigram/bigram。"""
    compact = _compact(text)
    terms: list[str] = []
    ascii_token = ""
    cjk: list[str] = []
    for char in compact:
        if char.isascii() and char.isalnum():
            ascii_token += char
            if cjk:
                terms.extend(cjk)
                terms.extend(a + b for a, b in zip(cjk, cjk[1:], strict=False))
                cjk = []
        else:
            if ascii_token:
                terms.append(ascii_token)
                ascii_token = ""
            cjk.append(char)
    if ascii_token:
        terms.append(ascii_token)
    if cjk:
        terms.extend(cjk)
        terms.extend(a + b for a, b in zip(cjk, cjk[1:], strict=False))
    return terms


def _cosine(left: list[float], right: list[float]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)
