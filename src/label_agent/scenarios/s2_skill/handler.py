"""S2 ScenarioHandler（§5.3）：委托 S2Pipeline 执行技能证书识别。"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.domain.models.s2_result import CertificateRecognitionResult
from label_agent.scenarios.s2_skill.pipeline import S2Pipeline


class S2SkillHandler:
    """S2 技能证书识别场景入口：委托 S2Pipeline 执行。"""

    scene = "S2"

    def __init__(self, pipeline: S2Pipeline) -> None:
        """注入 S2 管线实例。"""
        self._pipeline = pipeline

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        """判断当前 Job 是否属于 S2 场景。"""
        return envelope.v2.scene == self.scene

    async def run(self, ctx: JobContext) -> CertificateRecognitionResult:
        """执行 S2 技能证书识别并返回场景结果。"""
        return await self._pipeline.run(ctx)
