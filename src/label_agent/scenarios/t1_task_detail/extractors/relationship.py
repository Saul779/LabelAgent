"""relationship 分支提取器：提取 relation_target / relation_target_detail（§3.3.2）。"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.t1_result import TaskDetailResult
from label_agent.inference.t1_task_detail import BizTaskType, T1TaskDetailInference
from label_agent.scenarios.t1_task_detail.extractors.base import (
    extraction_error,
    perception_errors,
    require_accept_mode,
)


class RelationshipExtractor:
    """关系类任务详情抽取器。"""

    biz_task_type: BizTaskType = "relationship"

    def __init__(self, inference: T1TaskDetailInference) -> None:
        """注入抽取所需依赖。"""
        self._inference = inference

    async def extract(self, ctx: JobContext) -> TaskDetailResult:
        proposal = await self._inference.extract(ctx, self.biz_task_type)
        errors = perception_errors(ctx)
        if "AMBIGUOUS_RELATION_TARGET" in proposal.ambiguity_codes:
            errors.append(
                extraction_error(
                    "AMBIGUOUS_RELATION_TARGET",
                    "relation_target",
                    "任务中存在多个互斥目标，无法稳定判断寻找人还是其他事物",
                )
            )
        if proposal.relation_target is None or not (proposal.relation_target_detail or "").strip():
            errors.append(
                extraction_error(
                    "MISSING_EXPLICIT_RELATION_TARGET",
                    "relation_target",
                    "关系类任务未明确表达可同时确定类型和描述的目标",
                )
            )
        return TaskDetailResult(
            accept_mode=require_accept_mode(ctx),
            biz_task_type=self.biz_task_type,
            relation_target=proposal.relation_target,
            relation_target_detail=(proposal.relation_target_detail or "").strip() or None,
            extraction_errors=_deduplicate_errors(errors),
        )


def _deduplicate_errors(errors):
    by_code = {error.code: error for error in errors}
    return list(by_code.values())
