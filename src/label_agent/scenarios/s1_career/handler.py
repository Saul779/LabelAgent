"""S1 ScenarioHandler（§5.3）：委托 S1Pipeline 执行职业识别。"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.domain.models.s1_result import CareerRecognitionResult
from label_agent.scenarios.s1_career.pipeline import S1Pipeline


class S1CareerHandler:
    """S1 职业识别场景入口：委托 S1Pipeline 执行。"""

    scene = "S1"

    def __init__(self, pipeline: S1Pipeline) -> None:
        """注入 S1 管线实例。"""
        self._pipeline = pipeline

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        """判断当前 Job 是否属于 S1 场景。"""
        return envelope.v2.scene == self.scene

    async def run(self, ctx: JobContext) -> CareerRecognitionResult:
        """执行 S1 职业识别并返回场景结果。"""
        return await self._pipeline.run(ctx)
