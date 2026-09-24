"""归一化精确匹配召回。"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.candidate import TagCandidate
from label_agent.infrastructure.tag_service.client import TagServiceClient


class ExactMatcher:
    """精确匹配召回器：对归一化后的文本做标签名精确匹配。"""

    def __init__(self, tag_service: TagServiceClient) -> None:
        """初始化精确匹配器。"""
        self._tag_service = tag_service

    async def match(self, ctx: JobContext) -> list[TagCandidate]:
        """从 Tag Service 查询并仅保留标准名精确命中的候选。"""
        query = ctx.content_bundle.normalized_text if ctx.content_bundle else ""
        domain = str(ctx.payload.get("tag_domain") or "content")
        candidates = await self._tag_service.search_tags(query, domain)
        return [candidate for candidate in candidates if candidate.match_source == "exact"]
