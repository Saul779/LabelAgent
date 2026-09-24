"""T1 ScenarioHandler：按 biz_task_type 路由到对应 Extractor（§5.2）。"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.domain.models.t1_result import TaskDetailResult
from label_agent.inference.t1_task_detail import T1TaskDetailInference
from label_agent.perception.t1_content_loader import T1ContentLoader
from label_agent.scenarios.t1_task_detail.extractors.base import (
    ExtractorRegistry,
    require_accept_mode,
)


class T1TaskDetailHandler:
    """T1 任务详情抽取场景入口：按任务类型分发到具体 Extractor。"""

    scene = "T1"

    def __init__(
        self,
        extractor_registry: ExtractorRegistry,
        content_loader: T1ContentLoader,
        inference: T1TaskDetailInference,
    ) -> None:
        """注入文本/图片感知、自动分支判断与 Extractor 注册表。"""
        self._extractor_registry = extractor_registry
        self._content_loader = content_loader
        self._inference = inference

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        """判断当前 Job 是否属于 T1 场景。"""
        return envelope.v2.scene == self.scene or envelope.v1.payload_type == "task"

    async def run(self, ctx: JobContext) -> TaskDetailResult:
        """感知文本/图片，由 Agent 判断分支并提取对应重点字段。"""
        require_accept_mode(ctx)
        ctx.content_bundle = await self._content_loader.build(ctx)
        biz_task_type = await self._inference.classify(ctx)
        extractor = self._extractor_registry.resolve(biz_task_type)
        return await extractor.extract(ctx)
