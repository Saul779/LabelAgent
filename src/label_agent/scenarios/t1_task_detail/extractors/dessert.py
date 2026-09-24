"""兜底分支提取器；暂沿用现有业务编码 dessert，只提取 service_mode。"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.t1_result import TaskDetailResult
from label_agent.inference.t1_task_detail import BizTaskType, T1TaskDetailInference
from label_agent.scenarios.t1_task_detail.extractors.base import (
    extraction_error,
    perception_errors,
    require_accept_mode,
)


class DessertExtractor:
    """非关系类、非技能类任务的兜底提取器。"""

    biz_task_type: BizTaskType = "dessert"

    def __init__(self, inference: T1TaskDetailInference) -> None:
        """注入抽取所需依赖。"""
        self._inference = inference

    async def extract(self, ctx: JobContext) -> TaskDetailResult:
        proposal = await self._inference.extract(ctx, self.biz_task_type)
        errors = perception_errors(ctx)
        if "AMBIGUOUS_SERVICE_MODE" in proposal.ambiguity_codes:
            errors.append(
                extraction_error(
                    "AMBIGUOUS_SERVICE_MODE",
                    "service_mode",
                    "任务同时表达线下与非线下方式，不能强行二选一",
                )
            )
        elif proposal.service_mode is None:
            errors.append(
                extraction_error(
                    "MISSING_EXPLICIT_SERVICE_MODE",
                    "service_mode",
                    "任务未明确表达线下或非线下服务方式",
                )
            )
        return TaskDetailResult(
            accept_mode=require_accept_mode(ctx),
            biz_task_type=self.biz_task_type,
            service_mode=(
                None
                if "AMBIGUOUS_SERVICE_MODE" in proposal.ambiguity_codes
                else proposal.service_mode
            ),
            extraction_errors=_deduplicate_errors(errors),
        )


def _deduplicate_errors(errors):
    by_code = {error.code: error for error in errors}
    return list(by_code.values())
