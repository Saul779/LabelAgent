"""MVP 专用内存词表 + Embedding 相似度检索（InMemoryDomainVectorIndex）。

生产阶段可用 CandidateRetriever + Milvus 替换本组件，核心归并算法无需重写。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from label_agent.inference.embeddings.base import EmbeddingProvider


@dataclass(frozen=True)
class DictionaryItem:
    """领域词表条目：词条 ID、标准 ID、展示名与别名。"""

    id: str
    display_name: str
    aliases: tuple[str, ...] = ()
    canonical_id: str | None = None
    metadata: dict[str, Any] | None = None

    @property
    def resolved_canonical_id(self) -> str:
        return self.canonical_id or self.id

    @property
    def resolved_metadata(self) -> dict[str, Any]:
        """返回可安全展开到候选结构中的扩展元数据。"""
        return self.metadata or {}


@dataclass(frozen=True)
class DomainSearchHit:
    """单个向量召回项；同一词条的正式名和别名允许分别出现。"""

    item: DictionaryItem
    score: float
    matched_text: str
    dictionary_snapshot_version: str = ""


@dataclass(frozen=True)
class _IndexedEntry:
    """已向量化的索引条目（内部使用）。"""

    item: DictionaryItem
    text: str
    vector: list[float]


class InMemoryDomainVectorIndex:
    """MVP 内存词表向量索引：对 display_name/alias 建索引并支持 top1 相似度检索。"""

    def __init__(
        self,
        domain: str,
        items: list[DictionaryItem],
        embedding_provider: EmbeddingProvider,
        *,
        dictionary_snapshot_version: str = "",
    ) -> None:
        """持有词条与 Embedding Provider，待 build 后可检索。"""
        self.domain = domain
        self.dictionary_snapshot_version = dictionary_snapshot_version
        self._items = items
        self._embedding_provider = embedding_provider
        self._entries: list[_IndexedEntry] = []
        self._ready = False

    @classmethod
    def from_yaml(
        cls,
        path: str | Path,
        embedding_provider: EmbeddingProvider,
        *,
        domain: str | None = None,
    ) -> InMemoryDomainVectorIndex:
        """从 YAML fixture 加载词表并构造索引实例。"""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        resolved_domain = domain or str(data.get("domain") or "")
        if not resolved_domain:
            raise ValueError(f"词表缺少 domain: {path}")
        raw_items = data.get("items")
        if raw_items is None:
            raw_items = data.get("tags") or []
        items = [
            DictionaryItem(
                id=str(raw["id"]),
                display_name=str(raw["display_name"]),
                aliases=tuple(str(a) for a in (raw.get("aliases") or [])),
                canonical_id=str(raw.get("canonical_id") or raw["id"]),
                metadata=dict(raw.get("metadata") or {}),
            )
            for raw in raw_items
        ]
        return cls(
            domain=resolved_domain,
            items=items,
            embedding_provider=embedding_provider,
            dictionary_snapshot_version=str(data.get("dictionary_snapshot_version") or ""),
        )

    async def build(self) -> None:
        """对所有正式名与别名批量 Embedding，构建可检索向量表。"""
        texts: list[str] = []
        owners: list[DictionaryItem] = []
        for item in self._items:
            texts.append(item.display_name)
            owners.append(item)
            for alias in item.aliases:
                texts.append(alias)
                owners.append(item)
        vectors = await self._embedding_provider.embed(texts)
        if len(vectors) != len(texts):
            raise RuntimeError("Embedding 数量与词条文本不一致")
        self._entries = [
            _IndexedEntry(item=owner, text=text, vector=vector)
            for owner, text, vector in zip(owners, texts, vectors, strict=True)
        ]
        self._ready = True

    async def top1(self, query_text: str) -> tuple[DictionaryItem | None, float]:
        """对查询文本做向量相似度检索，返回最相似词条与分数。"""
        if not self._ready:
            await self.build()
        if not self._entries or not (query_text or "").strip():
            return None, 0.0
        query_vectors = await self._embedding_provider.embed([query_text.strip()])
        query = query_vectors[0]
        best_item: DictionaryItem | None = None
        best_score = -1.0
        for entry in self._entries:
            score = _cosine_similarity(query, entry.vector)
            if score > best_score:
                best_score = score
                best_item = entry.item
        # 夹紧到 [0, 1]，避免浮点误差产生略大于 1 的值（如 1.0000000000000002）
        return best_item, min(1.0, max(0.0, best_score))

    def find_exact(self, text: str) -> list[DomainSearchHit]:
        """按正式名/别名做空白归一后的精确命中，分数记为 1.0。"""
        needle = _normalize_lookup_text(text)
        if not needle or not self._entries:
            return []
        return [
            DomainSearchHit(
                item=entry.item,
                score=1.0,
                matched_text=entry.text,
                dictionary_snapshot_version=self.dictionary_snapshot_version,
            )
            for entry in self._entries
            if _normalize_lookup_text(entry.text) == needle
        ]

    async def top_k(self, query_text: str, k: int = 5) -> list[DomainSearchHit]:
        """返回 entry 级 Top-k，不按词条或 canonical_id 去重。"""
        if k <= 0:
            return []
        if not self._ready:
            await self.build()
        if not self._entries or not (query_text or "").strip():
            return []
        query_vectors = await self._embedding_provider.embed([query_text.strip()])
        query = query_vectors[0]
        scored = [
            DomainSearchHit(
                item=entry.item,
                score=min(1.0, max(0.0, _cosine_similarity(query, entry.vector))),
                matched_text=entry.text,
                dictionary_snapshot_version=self.dictionary_snapshot_version,
            )
            for entry in self._entries
        ]
        scored.sort(key=lambda hit: hit.score, reverse=True)
        return scored[:k]

    def as_dict_snapshot(self) -> dict[str, Any]:
        """导出词表快照元信息（领域、版本、规模）。"""
        return {
            "domain": self.domain,
            "dictionary_snapshot_version": self.dictionary_snapshot_version,
            "size": len(self._items),
        }


def _normalize_lookup_text(text: str) -> str:
    """去掉空白，便于「Python 开发工程师」与「Python开发工程师」对齐。"""
    return "".join((text or "").split())


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两向量余弦相似度。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)
