"""S3 管线编排（§5.1.1）。

LOAD -> PERCEPTION -> CANDIDATE RETRIEVAL -> SEMANTIC PROPOSAL(LLM)
 -> ENTITY RESOLUTION -> PRE-VALIDATION -> TAG COMMIT
 -> VECTORIZE(新标签) -> POST-VALIDATION -> PUBLISH

关键约束：创建/写入操作只能发生在 PRE-VALIDATION 通过之后，
本文件只做阶段编排，不直接持有基础设施客户端（通过 di.Container 注入）。
"""

from __future__ import annotations

import asyncio

from label_agent.core.context import JobContext
from label_agent.core.exceptions import RetryableError
from label_agent.domain.models.s3_result import ContentLabelResult
from label_agent.embedding.vector_consistency import is_publishable
from label_agent.inference.semantic_proposer import SemanticProposer
from label_agent.perception.content_bundle_builder import ContentBundleBuilder
from label_agent.resolution.entity_resolver import EntityResolver
from label_agent.resolution.tag_committer import TagCommitter
from label_agent.retrieval.candidate_retriever import CandidateRetriever
from label_agent.validation.post_validation import PostValidator
from label_agent.validation.pre_validation import PreValidator


class S3Pipeline:
    """S3 内容打标主管线：感知 -> 召回 -> 语义提议 -> 归一 -> 校验。"""

    def __init__(
        self,
        content_bundle_builder: ContentBundleBuilder,
        candidate_retriever: CandidateRetriever,
        semantic_proposer: SemanticProposer,
        entity_resolver: EntityResolver,
        pre_validator: PreValidator,
        tag_committer: TagCommitter,
        post_validator: PostValidator,
    ) -> None:
        """注入感知、召回、提议、归一与校验等依赖。"""
        self._content_bundle_builder = content_bundle_builder
        self._candidate_retriever = candidate_retriever
        self._semantic_proposer = semantic_proposer
        self._entity_resolver = entity_resolver
        self._pre_validator = pre_validator
        self._tag_committer = tag_committer
        self._post_validator = post_validator

    async def run(self, ctx: JobContext) -> ContentLabelResult:
        """执行 S3 全流程并产出内容打标结果。"""
        ctx.content_bundle = await self._content_bundle_builder.build(ctx)
        for modality in ctx.content_bundle.failed_modalities:
            ctx.note_degraded(modality)
        domain = str(ctx.payload.get("tag_domain") or "content")
        category_candidates, tag_candidates = await asyncio.gather(
            self._candidate_retriever.retrieve_categories(ctx, domain),
            self._candidate_retriever.retrieve(ctx),
        )
        ctx.category_candidates = category_candidates
        ctx.candidates = tag_candidates
        ctx.semantic_proposal = await self._semantic_proposer.propose(ctx)
        ctx.resolved_entities = self._entity_resolver.resolve(ctx)

        self._pre_validator.validate(ctx)  # 写操作前置校验，早于任何 Tag Service 写入

        result = await self._tag_committer.commit(ctx)

        self._post_validator.validate(ctx, result)
        if not is_publishable(result):
            # 新建标签向量仍为 PENDING，Job 进入重试等待，不发布（§6.3）
            raise NeedReviewOrRetry(result)
        return result


class NeedReviewOrRetry(RetryableError):
    """新标签向量尚未就绪，要求 JobWorker 延迟重试。"""

    error_code = "TAG_VECTOR_PENDING"

    def __init__(self, result: ContentLabelResult) -> None:
        """携带复核/重试原因。"""
        super().__init__("存在向量未 READY 的新建标签，暂不发布（§6.3）")
        self.result = result
