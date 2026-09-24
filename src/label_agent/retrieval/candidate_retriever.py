"""CandidateRetriever：多路召回 + RRF 融合入口（§5.1.3）。

召回失败或候选为空时，允许提出 new_tag_requested，交由 EntityResolver
判断是否满足创建条件（§6.2）。
"""

from __future__ import annotations

import asyncio

from label_agent.core.context import JobContext
from label_agent.domain.models.candidate import CategoryCandidate, TagCandidate
from label_agent.infrastructure.tag_service.client import TagServiceClient
from label_agent.retrieval.fusion.rrf import reciprocal_rank_fusion
from label_agent.retrieval.matchers.alias_match import AliasMatcher
from label_agent.retrieval.matchers.bm25_match import Bm25Matcher
from label_agent.retrieval.matchers.exact_match import ExactMatcher
from label_agent.retrieval.matchers.vector_match import TagServiceVectorMatcher, VectorMatcher


class CandidateRetriever:
    """多路召回编排器：并行调用精确/别名/BM25/向量四路匹配器并通过 RRF 融合排序。"""

    def __init__(
        self,
        tag_service: TagServiceClient,
        exact_matcher: ExactMatcher,
        alias_matcher: AliasMatcher | None = None,
        bm25_matcher: Bm25Matcher | None = None,
        vector_matcher: VectorMatcher | TagServiceVectorMatcher | None = None,
        *,
        max_candidates: int = 20,
    ) -> None:
        """注入多路匹配器与融合策略，供 S3 候选召回。"""
        self._tag_service = tag_service
        self._exact_matcher = exact_matcher
        self._alias_matcher = alias_matcher
        self._bm25_matcher = bm25_matcher
        self._vector_matcher = vector_matcher
        self._max_candidates = max_candidates

    async def retrieve(self, ctx: JobContext) -> list[TagCandidate]:
        """并行执行已装配的召回器，再用 RRF 融合并按上限截断候选。"""
        matchers = [
            matcher
            for matcher in (
                self._exact_matcher,
                self._alias_matcher,
                self._bm25_matcher,
                self._vector_matcher,
            )
            if matcher is not None
        ]
        result_lists = await asyncio.gather(*(matcher.match(ctx) for matcher in matchers))
        return reciprocal_rank_fusion(list(result_lists))[: self._max_candidates]

    async def retrieve_categories(self, ctx: JobContext, domain: str) -> list[CategoryCandidate]:
        """从 Tag Service 读取指定领域的分类候选；分类只读且禁止创建。"""
        _ = ctx
        return await self._tag_service.search_categories(domain)
