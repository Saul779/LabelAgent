"""n-gram/BM25 召回。"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.candidate import TagCandidate
from label_agent.infrastructure.tag_service.client import TagServiceClient


class Bm25Matcher:
    """BM25 文本召回匹配器。"""

    def __init__(self, tag_service: TagServiceClient) -> None:
        """注入 Tag Service，供 BM25 召回查询标签候选。"""
        self._tag_service = tag_service

    async def match(self, ctx: JobContext) -> list[TagCandidate]:
        """从 Tag Service 查询并仅保留 BM25/n-gram 模糊命中的候选。"""
        query = ctx.content_bundle.normalized_text if ctx.content_bundle else ""
        domain = str(ctx.payload.get("tag_domain") or "content")
        candidates = await self._tag_service.search_tags(query, domain)
        return [candidate for candidate in candidates if candidate.match_source == "bm25"]
