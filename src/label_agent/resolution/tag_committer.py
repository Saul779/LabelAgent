"""TagCommitter：唯一允许写 Tag Service 的组件（§5.1.5、§6.2、§6.3）。

创建新标签前必须先经过 validation.safety 的安全门禁，遵循
“写操作前置校验”原则——不得先创建再校验。
"""

from __future__ import annotations

import hashlib

from label_agent.core.context import JobContext
from label_agent.domain.errors import InvalidProposalError
from label_agent.domain.models.candidate import CategoryCandidate, TagCandidate
from label_agent.domain.models.proposal import ProposedCategory, ProposedTag
from label_agent.domain.models.s3_result import (
    CategoryResult,
    ContentLabelResult,
    TagResult,
)
from label_agent.domain.models.tag import Tag
from label_agent.infrastructure.tag_service.client import TagServiceClient
from label_agent.validation.new_tag_safety import normalize_tag_name


class TagCommitter:
    """标签落库/回写协调器：将确认后的标签提交到 Tag Service。"""

    def __init__(
        self,
        tag_service: TagServiceClient,
        *,
        auto_create: bool = False,
        confidence_threshold: float = 0.5,
        policy_version: str = "provisional-rule-mvp-1",
        dictionary_snapshot_version: str = "",
    ) -> None:
        """注入 Tag Service 客户端等写路径依赖。"""
        self._tag_service = tag_service
        self._auto_create = auto_create
        self._confidence_threshold = confidence_threshold
        self._policy_version = policy_version
        self._dictionary_snapshot_version = dictionary_snapshot_version

    async def commit(self, ctx: JobContext) -> ContentLabelResult:
        """复用已有标签或按已通过预校验的请求执行幂等创建。"""
        if ctx.semantic_proposal is None:
            raise InvalidProposalError("TagCommitter 之前必须先完成语义提议")

        candidate_by_id = {candidate.tag_id: candidate for candidate in ctx.candidates}
        tag_results: list[TagResult] = []
        for proposal in ctx.resolved_entities:
            if proposal.model_score < self._confidence_threshold:
                continue
            if proposal.tag_id is not None:
                candidate = candidate_by_id[proposal.tag_id]
                tag_results.append(self._matched_tag_result(candidate, proposal))
                continue
            if proposal.new_tag_request is None or not self._auto_create:
                continue
            tag_results.append(await self._resolve_or_create_tag(proposal))

        tag_results.sort(key=lambda item: item.final_confidence, reverse=True)
        primary = self._resolve_primary_category(ctx)
        secondary = self._resolve_secondary_category(ctx, primary)
        snapshot = self._resolve_dictionary_snapshot(ctx)
        ctx.policy_version = self._policy_version
        return ContentLabelResult(
            biz_id=ctx.biz_id,
            data_version=ctx.data_version,
            result_revision=int(ctx.payload.get("result_revision") or 1),
            dictionary_snapshot_version=snapshot,
            model_run_id=ctx.semantic_proposal.model_run_id,
            prompt_version=ctx.semantic_proposal.prompt_version,
            policy_version=self._policy_version,
            primary_category=primary,
            secondary_category=secondary,
            tags=tag_results[:5],
            degraded_modalities=list(ctx.degraded_modalities),
            perception_versions=(
                dict(ctx.content_bundle.perception_versions) if ctx.content_bundle else {}
            ),
        )

    def _matched_tag_result(
        self,
        candidate: TagCandidate,
        proposal: ProposedTag,
    ) -> TagResult:
        """把已召回标签和模型分数组装为正式的 matched 标签结果。"""
        return TagResult(
            tag_id=candidate.tag_id,
            canonical_tag_id=candidate.canonical_tag_id,
            display_name=candidate.display_name,
            name_type=candidate.name_type,
            source="matched",
            model_score=proposal.model_score,
            final_confidence=proposal.model_score,
            evidence_refs=list(proposal.evidence_refs),
            vector_state=candidate.vector_state,
        )

    async def _resolve_or_create_tag(self, proposal: ProposedTag) -> TagResult:
        """对已通过预校验的新标签查重，再按幂等键创建并转换结果。"""
        request = proposal.new_tag_request
        if request is None:
            raise InvalidProposalError("新标签提议缺少 new_tag_request")
        duplicates = await self._tag_service.search_tags(request.proposed_name, request.domain)
        reusable = next(
            (candidate for candidate in duplicates if candidate.match_source in {"exact", "alias"}),
            None,
        )
        if reusable is not None:
            return self._matched_tag_result(reusable, proposal)

        normalized_name = normalize_tag_name(request.proposed_name)
        idempotency_key = hashlib.sha256(
            (f"{request.domain}|{normalized_name}|" f"{self._dictionary_snapshot_version}").encode()
        ).hexdigest()
        created = await self._tag_service.create_tag(
            request.proposed_name.strip(),
            request.domain,
            idempotency_key,
        )
        return self._created_tag_result(created, proposal)

    @staticmethod
    def _created_tag_result(created: Tag, proposal: ProposedTag) -> TagResult:
        """把 Tag Service 新建标签实体转换为 source=created 的结果条目。"""
        return TagResult(
            tag_id=created.tag_id,
            canonical_tag_id=created.canonical_tag_id,
            display_name=created.display_name,
            name_type=created.name_type,
            source="created",
            model_score=proposal.model_score,
            final_confidence=proposal.model_score,
            evidence_refs=list(proposal.evidence_refs),
            vector_state=created.vector_state.value,
        )

    def _resolve_primary_category(self, ctx: JobContext) -> CategoryResult:
        """按阈值解析一级分类；无可靠候选时固定回退“未分类”。"""
        semantic_proposal = ctx.semantic_proposal
        if semantic_proposal is None:
            raise InvalidProposalError("分类组装前必须存在 SemanticProposal")
        proposal = semantic_proposal.primary_category
        candidate = self._find_category(ctx, proposal, expected_level=1)
        if (
            proposal is None
            or candidate is None
            or proposal.model_score < self._confidence_threshold
        ):
            return self._uncategorized_result(ctx)
        return self._category_result(candidate, proposal)

    def _resolve_secondary_category(
        self,
        ctx: JobContext,
        primary: CategoryResult,
    ) -> CategoryResult | None:
        """解析可选二级分类，并校验其父分类与最终一级分类一致。"""
        if primary.name == "未分类":
            return None
        semantic_proposal = ctx.semantic_proposal
        if semantic_proposal is None:
            raise InvalidProposalError("分类组装前必须存在 SemanticProposal")
        proposal = semantic_proposal.secondary_category
        candidate = self._find_category(ctx, proposal, expected_level=2)
        if (
            proposal is None
            or candidate is None
            or proposal.model_score < self._confidence_threshold
        ):
            return None
        if candidate.parent_category_id and candidate.parent_category_id != primary.category_id:
            return None
        return self._category_result(candidate, proposal)

    @staticmethod
    def _find_category(
        ctx: JobContext,
        proposal: ProposedCategory | None,
        *,
        expected_level: int,
    ) -> CategoryCandidate | None:
        """从上下文候选中查找指定层级和 ID 的分类。"""
        if proposal is None:
            return None
        return next(
            (
                candidate
                for candidate in ctx.category_candidates
                if candidate.category_id == proposal.category_id
                and candidate.level == expected_level
            ),
            None,
        )

    @staticmethod
    def _category_result(
        candidate: CategoryCandidate,
        proposal: ProposedCategory,
    ) -> CategoryResult:
        """把分类候选和模型提议转换为最终分类结果。"""
        return CategoryResult(
            category_id=candidate.category_id,
            name=candidate.name,
            confidence=proposal.model_score,
            evidence_refs=list(proposal.evidence_refs),
        )

    @staticmethod
    def _uncategorized_result(ctx: JobContext) -> CategoryResult:
        """从词表定位“未分类”，词表缺失时使用稳定兜底 ID。"""
        candidate = next(
            (item for item in ctx.category_candidates if item.level == 1 and item.name == "未分类"),
            None,
        )
        return CategoryResult(
            category_id=(candidate.category_id if candidate else "category-uncategorized"),
            name="未分类",
            confidence=0.0,
            evidence_refs=[],
        )

    def _resolve_dictionary_snapshot(self, ctx: JobContext) -> str:
        """优先从本次候选提取词表快照版本，空候选时使用装配配置。"""
        all_candidates = [*ctx.category_candidates, *ctx.candidates]
        if all_candidates:
            return str(all_candidates[0].dictionary_snapshot_version)
        return self._dictionary_snapshot_version
