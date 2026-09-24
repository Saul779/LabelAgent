"""ScenarioRegistry 场景注册与解析测试。"""

from __future__ import annotations

import pytest

from label_agent.domain.models.envelope import EnvelopeV2Extension, ParsedEnvelope, TaskEnvelopeV1
from label_agent.scenarios.registry import ScenarioRegistry, UnresolvedScenarioError


class _StubHandler:
    def __init__(self, scene: str) -> None:
        self.scene = scene

    def can_handle(self, envelope: ParsedEnvelope) -> bool:
        return envelope.v2.scene == self.scene

    async def run(self, ctx):  # noqa: ANN001 - 测试桩不需要严格类型
        return {"scene": self.scene}


def _envelope(scene: str) -> ParsedEnvelope:
    v1 = TaskEnvelopeV1(
        task_id="task-1",
        task_type="mark_tag",
        payload_type="dynamic",
        payload={},
        priority=2,
        timestamp=1,
        callback_topic="agent.task.callback",
    )
    return ParsedEnvelope(v1=v1, v2=EnvelopeV2Extension(scene=scene))


def test_registered_scenario_resolved() -> None:
    registry = ScenarioRegistry()
    registry.register(_StubHandler(scene="S1"))

    handler = registry.resolve(_envelope("S1"))

    assert handler.scene == "S1"


def test_unregistered_scenario_rejected() -> None:
    registry = ScenarioRegistry()
    registry.register(_StubHandler(scene="S3"))

    with pytest.raises(UnresolvedScenarioError):
        registry.resolve(_envelope("S1"))
