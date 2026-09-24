"""T1 自动三分类与分支提取集成测试。"""

from __future__ import annotations

import json

import pytest

from label_agent.core.context import JobContext
from label_agent.domain.models.content import ContentBundle
from label_agent.domain.models.envelope import EnvelopeV2Extension, ParsedEnvelope, TaskEnvelopeV1
from label_agent.domain.models.job import JobOutcome
from label_agent.inference.providers.base import ModelCompletionResult
from label_agent.inference.t1_task_detail import T1TaskDetailInference
from label_agent.scenarios.t1_task_detail.extractors.base import (
    ExtractorRegistry,
    InvalidAcceptModeError,
)
from label_agent.scenarios.t1_task_detail.extractors.dessert import DessertExtractor
from label_agent.scenarios.t1_task_detail.extractors.relationship import RelationshipExtractor
from label_agent.scenarios.t1_task_detail.extractors.skill import SkillExtractor
from label_agent.scenarios.t1_task_detail.handler import T1TaskDetailHandler


class _StaticLoader:
    async def build(self, ctx: JobContext) -> ContentBundle:
        return ContentBundle(normalized_text=str(ctx.payload.get("text") or ""))


class _PromptManager:
    def render(self, scene: str, prompt_version: str, variables: dict) -> tuple[str, str]:
        return prompt_version, json.dumps(variables, ensure_ascii=False)


class _Gateway:
    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.requests = []

    async def complete(self, request, model_alias=None):
        _ = model_alias
        self.requests.append(request)
        return ModelCompletionResult(
            raw_text=self.responses.pop(0),
            model_name="fake",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
        )


def _handler(responses: list[str]) -> T1TaskDetailHandler:
    inference = T1TaskDetailInference(
        _Gateway(responses),  # type: ignore[arg-type]
        _PromptManager(),  # type: ignore[arg-type]
    )
    registry = ExtractorRegistry()
    registry.register(RelationshipExtractor(inference))
    registry.register(SkillExtractor(inference))
    registry.register(DessertExtractor(inference))
    return T1TaskDetailHandler(
        registry,
        _StaticLoader(),  # type: ignore[arg-type]
        inference,
    )


def _ctx(text: str) -> JobContext:
    return JobContext(
        job_id="j-t1",
        task_id="t-t1",
        scene="T1",
        biz_id="biz-t1",
        payload={"accept_mode": "public", "text": text},
    )


@pytest.mark.asyncio
async def test_t1_agent_classifies_relationship_and_extracts_target() -> None:
    handler = _handler(
        [
            '{"biz_task_type":"relationship"}',
            json.dumps(
                {
                    "relation_target": "person",
                    "relation_target_detail": "会照顾宠物的人",
                    "required_skills": [],
                    "service_mode": None,
                    "ambiguity_codes": [],
                },
                ensure_ascii=False,
            ),
        ]
    )

    result = await handler.run(_ctx("寻找一位会照顾宠物的人"))

    assert result.biz_task_type == "relationship"
    assert result.relation_target == "person"
    assert result.relation_target_detail == "会照顾宠物的人"
    assert result.to_job_outcome() is JobOutcome.SUCCEEDED


@pytest.mark.asyncio
async def test_t1_agent_classifies_skill_and_marks_missing_service_mode_partial() -> None:
    handler = _handler(
        [
            '{"biz_task_type":"skill"}',
            json.dumps(
                {
                    "relation_target": None,
                    "relation_target_detail": None,
                    "required_skills": ["电脑维修", "电脑维修"],
                    "service_mode": None,
                    "ambiguity_codes": [],
                },
                ensure_ascii=False,
            ),
        ]
    )

    result = await handler.run(_ctx("需要维修电脑"))

    assert result.biz_task_type == "skill"
    assert result.required_skills == ["电脑维修"]
    assert [item.code for item in result.extraction_errors] == ["MISSING_EXPLICIT_SERVICE_MODE"]
    assert result.to_job_outcome() is JobOutcome.PARTIAL_SUCCESS


@pytest.mark.asyncio
async def test_t1_fallback_does_not_force_mixed_service_mode() -> None:
    handler = _handler(
        [
            '{"biz_task_type":"dessert"}',
            json.dumps(
                {
                    "relation_target": None,
                    "relation_target_detail": None,
                    "required_skills": [],
                    "service_mode": None,
                    "ambiguity_codes": ["AMBIGUOUS_SERVICE_MODE"],
                },
                ensure_ascii=False,
            ),
        ]
    )

    result = await handler.run(_ctx("可以远程，也可以到店处理"))

    assert result.biz_task_type == "dessert"
    assert result.service_mode is None
    assert result.extraction_errors[0].code == "AMBIGUOUS_SERVICE_MODE"
    assert result.to_job_outcome() is JobOutcome.NEED_REVIEW


def test_t1_handler_matches_explicit_scene_or_legacy_task_payload() -> None:
    handler = _handler(['{"biz_task_type":"dessert"}'])
    explicit = ParsedEnvelope(
        v1=TaskEnvelopeV1(
            task_id="t",
            task_type="mark_tag",
            payload_type="unknown",
            payload={},
            priority=1,
            timestamp=1,
            callback_topic="receipt",
        ),
        v2=EnvelopeV2Extension(scene="T1"),
    )
    legacy = explicit.model_copy(
        update={
            "v1": explicit.v1.model_copy(update={"payload_type": "task"}),
            "v2": EnvelopeV2Extension(scene=None),
        }
    )

    assert handler.can_handle(explicit)
    assert handler.can_handle(legacy)


@pytest.mark.asyncio
@pytest.mark.parametrize("value", [None, "", "open", "PUBLIC"])
async def test_t1_rejects_invalid_accept_mode_before_perception(value) -> None:
    handler = _handler([])
    ctx = _ctx("测试任务")
    ctx.payload["accept_mode"] = value

    with pytest.raises(InvalidAcceptModeError) as exc_info:
        await handler.run(ctx)

    assert exc_info.value.error_code == "T1_INVALID_ACCEPT_MODE"
