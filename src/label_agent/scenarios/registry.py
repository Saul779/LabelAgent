"""ScenarioRegistry（§2.3）：场景注册与路由解析。"""

from __future__ import annotations

from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.scenarios.base import ScenarioHandler


class UnresolvedScenarioError(NonRetryableError):
    """无法解析到对应场景 Handler 时抛出。"""

    error_code = "UNRESOLVED_SCENARIO"


class ScenarioRegistry:
    """场景 Handler 注册表：按 scene 查找并分发。"""

    def __init__(self) -> None:
        """初始化空注册表。"""
        self._handlers: dict[str, ScenarioHandler] = {}

    def register(self, handler: ScenarioHandler) -> None:
        """注册一个场景 Handler。"""
        self._handlers[handler.scene] = handler

    def resolve(self, envelope: ParsedEnvelope) -> ScenarioHandler:
        """按 scene 解析 Handler，找不到则报错。"""
        scene = envelope.v2.scene
        if scene:
            handler = self._handlers.get(scene)
            if handler is not None:
                return handler
        raise UnresolvedScenarioError(f"未找到可处理该信封的场景: {scene}")
