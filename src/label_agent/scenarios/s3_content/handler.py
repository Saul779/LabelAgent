"""S3 ScenarioHandler：动态内容分类与标签（§5.1）。"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.domain.models.s3_result import ContentLabelResult
from label_agent.scenarios.s3_content.pipeline import S3Pipeline


class S3ContentHandler:
    """S3 内容打标场景入口：委托 S3Pipeline 执行。"""

    scene = "S3"

    def __init__(self, pipeline: S3Pipeline) -> None:
        """注入 S3 管线实例。"""
        self._pipeline = pipeline

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        """判断当前 Job 是否属于 S3 场景。"""
        return envelope.v2.scene == self.scene or envelope.v1.payload_type in {"dynamic"}

    async def run(self, ctx: JobContext) -> ContentLabelResult:
        """执行 S3 内容打标并返回场景结果。"""
        return await self._pipeline.run(ctx)
