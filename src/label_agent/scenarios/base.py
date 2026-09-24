"""ScenarioHandler 协议（§2.3）。"""

from __future__ import annotations

from typing import Protocol

from label_agent.core.context import JobContext
from label_agent.domain.models.envelope import ParsedEnvelope


class ScenarioResult(Protocol):
    """各场景输出的公共承诺：必须能序列化为回执 payload。"""

    def to_receipt_payload(self) -> dict: ...


class ScenarioHandler(Protocol):
    """场景处理器协议：判断能否处理并执行场景管线。"""

    scene: str  # S1 | S2 | S3 | S4 | T1

    def can_handle(self, envelope: ParsedEnvelope) -> bool: ...

    async def run(self, ctx: JobContext) -> ScenarioResult: ...
