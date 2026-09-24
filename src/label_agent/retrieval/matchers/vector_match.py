"""MVP 内存向量近义检索召回。"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.candidate import TagCandidate
from label_agent.infrastructure.tag_service.client import TagServiceClient
from label_agent.retrieval.generative_domain_index import InMemoryDomainVectorIndex


class VectorMatcher:
    """基于内存领域索引的向量相似度召回匹配器。"""

    def __init__(
        self,
        index: InMemoryDomainVectorIndex,
        *,
        top_k: int = 20,
        min_score: float = 0.0,
    ) -> None:
        """注入已配置 Embedding Provider 的内存索引。"""
        if top_k <= 0:
            raise ValueError("top_k 必须大于 0")
        if not 0.0 <= min_score <= 1.0:
            raise ValueError("min_score 必须在 [0, 1] 范围内")
        self._index = index
        self._top_k = top_k
        self._min_score = min_score

    async def match(self, ctx: JobContext) -> list[TagCandidate]:
        """向量检索标签，并按 canonical_tag_id 去重。"""
        query = ctx.content_bundle.normalized_text if ctx.content_bundle else ""
        domain = str(ctx.payload.get("tag_domain") or "content")
        if domain != self._index.domain or not query.strip():
            return []

        hits = await self._index.top_k(query, self._top_k)
        candidates: dict[str, TagCandidate] = {}
        for hit in hits:
            if hit.score < self._min_score:
                continue
            item = hit.item
            canonical_id = item.resolved_canonical_id
            candidate = TagCandidate(
                tag_id=item.id,
                canonical_tag_id=canonical_id,
                display_name=item.display_name,
                name_type=("standard" if hit.matched_text == item.display_name else "alias"),
                domain=self._index.domain,
                dictionary_snapshot_version=self._index.dictionary_snapshot_version,
                match_source="vector",
                match_score=hit.score,
                vector_state="READY",
            )
            current = candidates.get(canonical_id)
            if current is None or candidate.match_score > current.match_score:
                candidates[canonical_id] = candidate

        return sorted(
            candidates.values(),
            key=lambda candidate: candidate.match_score,
            reverse=True,
        )


class TagServiceVectorMatcher:
    """从生产 Tag Service 的统一搜索接口提取向量召回通道。"""

    def __init__(self, tag_service: TagServiceClient) -> None:
        self._tag_service = tag_service

    async def match(self, ctx: JobContext) -> list[TagCandidate]:
        query = ctx.content_bundle.normalized_text if ctx.content_bundle else ""
        domain = str(ctx.payload.get("tag_domain") or "content")
        candidates = await self._tag_service.search_tags(query, domain)
        return [candidate for candidate in candidates if candidate.match_source == "vector"]
