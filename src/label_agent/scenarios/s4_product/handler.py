"""S4 商品打标场景入口。"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.domain.models.s4_result import ProductLabelResult
from label_agent.scenarios.s4_product.pipeline import S4ProductPipeline


class S4ProductHandler:
    scene = "S4"

    def __init__(self, pipeline: S4ProductPipeline) -> None:
        self._pipeline = pipeline

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        return envelope.v2.scene == self.scene or envelope.v1.payload_type == "product"

    async def run(self, ctx: JobContext) -> ProductLabelResult:
        return await self._pipeline.run(ctx)
