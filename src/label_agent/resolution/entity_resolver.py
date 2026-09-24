"""EntityResolver：纯函数，无副作用（§5.1.5、§6.1）。

职责：
- 校验 SemanticProposal 引用的候选 ID 是否存在于 ctx.candidates；
- 按 canonical_tag_id 归并去重（同簇只保留 final_confidence 最高的一条）；
- 判断 new_tag_requested 是否进入创建流程（不在本类执行创建，创建属于 TagCommitter）。
"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.errors import InvalidProposalError
from label_agent.domain.models.candidate import CategoryCandidate
from label_agent.domain.models.proposal import ProposedCategory, ProposedTag
from label_agent.resolution.dedup import dedup_by_canonical_tag


class EntityResolver:
    """S3 实体归一：将语义提议中的候选映射为正式标签/类目 ID。"""

    def resolve(self, ctx: JobContext) -> list[ProposedTag]:
        """对提议结果执行实体解析与冲突处理。"""
        if ctx.semantic_proposal is None:
            raise InvalidProposalError("resolve 之前必须先完成语义提议阶段")
        category_by_id = {candidate.category_id: candidate for candidate in ctx.category_candidates}
        self._validate_category(
            ctx.semantic_proposal.primary_category,
            category_by_id,
            expected_level=1,
        )
        self._validate_category(
            ctx.semantic_proposal.secondary_category,
            category_by_id,
            expected_level=2,
        )
        canonical_of = {c.tag_id: c.canonical_tag_id for c in ctx.candidates}
        for tag in ctx.semantic_proposal.tags:
            if tag.tag_id is not None and tag.tag_id not in canonical_of:
                raise InvalidProposalError(f"模型引用了不存在的候选 tag_id: {tag.tag_id}")
            if tag.tag_id is None and tag.new_tag_request is None:
                raise InvalidProposalError("标签提议必须引用候选 tag_id 或提供 new_tag_request")
            if tag.tag_id is not None and tag.new_tag_request is not None:
                raise InvalidProposalError("标签提议不能同时包含 tag_id 与 new_tag_request")
        return dedup_by_canonical_tag(ctx.semantic_proposal.tags, canonical_of)

    @staticmethod
    def _validate_category(
        proposal: ProposedCategory | None,
        category_by_id: dict[str, CategoryCandidate],
        *,
        expected_level: int,
    ) -> None:
        """校验分类提议引用存在的候选，并确保一级/二级层级没有混用。"""
        if proposal is None:
            return
        candidate = category_by_id.get(proposal.category_id)
        if candidate is None:
            raise InvalidProposalError(
                f"模型引用了不存在的候选 category_id: {proposal.category_id}"
            )
        if candidate.level != expected_level:
            raise InvalidProposalError(
                f"分类 {proposal.category_id} 层级错误，期望 level={expected_level}"
            )
