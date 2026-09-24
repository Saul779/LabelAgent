"""S1/S2 生产领域索引：将 Tag Service 候选适配为证据匹配候选。"""

from __future__ import annotations

from label_agent.infrastructure.tag_service.client import TagServiceClient
from label_agent.retrieval.generative_domain_index import DictionaryItem, DomainSearchHit


class TagServiceDomainIndex:
    """通过 Tag Service 检索正式职业/证书词典，不在进程内维护词典副本。"""

    def __init__(self, domain: str, tag_service: TagServiceClient) -> None:
        if domain not in {"career", "certificate"}:
            raise ValueError(f"不支持的证据匹配领域: {domain}")
        self.domain = domain
        self.dictionary_snapshot_version = ""
        self._tag_service = tag_service

    async def top_k(self, query_text: str, k: int = 5) -> list[DomainSearchHit]:
        """调用统一搜索接口，并按精确、别名、向量、文本召回顺序截取 Top-K。"""
        if k <= 0 or not query_text.strip():
            return []
        candidates = await self._tag_service.search_tags(query_text.strip(), self.domain)
        source_priority = {"exact": 0, "alias": 1, "vector": 2, "bm25": 3}
        usable = [
            candidate
            for candidate in candidates
            if candidate.domain == self.domain and candidate.vector_state == "READY"
        ]
        usable.sort(
            key=lambda candidate: (
                source_priority.get(candidate.match_source, 9),
                -candidate.match_score,
            )
        )

        hits: list[DomainSearchHit] = []
        seen: set[tuple[str, str]] = set()
        for candidate in usable:
            key = (candidate.tag_id, candidate.display_name)
            if key in seen:
                continue
            seen.add(key)
            display_name = candidate.canonical_display_name or candidate.display_name
            hits.append(
                DomainSearchHit(
                    item=DictionaryItem(
                        id=candidate.tag_id,
                        display_name=display_name,
                        canonical_id=candidate.canonical_tag_id,
                        metadata=candidate.metadata,
                    ),
                    score=candidate.match_score,
                    matched_text=candidate.display_name,
                    dictionary_snapshot_version=candidate.dictionary_snapshot_version,
                )
            )
            if len(hits) >= k:
                break
        return hits

    def find_exact(self, text: str) -> list[DomainSearchHit]:
        """精确通道已由 Tag Service 在 top_k 响应中返回并被优先排序。"""
        _ = text
        return []
