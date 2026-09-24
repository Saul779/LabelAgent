"""GenerativeProposer JSON 解析与重试。"""

from __future__ import annotations

import pytest

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NeedReviewError
from label_agent.domain.models.content import ContentBundle
from label_agent.inference.generative_proposer import GenerativeProposer
from label_agent.inference.providers.base import ModelCompletionResult


class _FakePromptManager:
    def render(self, scene: str, prompt_version: str, variables: dict) -> tuple[str, str]:
        return "system", f"user:{variables.get('normalized_text')}"


class _FakeGateway:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0

    async def complete(self, request, model_alias: str | None = None):
        _ = request, model_alias
        text = self._responses[min(self.calls, len(self._responses) - 1)]
        self.calls += 1
        return ModelCompletionResult(
            raw_text=text,
            model_name="fake",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
        )


def _ctx() -> JobContext:
    return JobContext(
        job_id="j1",
        task_id="t1",
        scene="S2",
        biz_id="b1",
        payload={},
        content_bundle=ContentBundle(normalized_text="熟悉 MySQL 与 Redis"),
    )


@pytest.mark.asyncio
async def test_parse_valid_json() -> None:
    gateway = _FakeGateway(
        [
            '{"candidates":[{"display_name":"MySQL","model_score":0.9},'
            '{"display_name":"Redis","model_score":0.8}]}'
        ]
    )
    proposer = GenerativeProposer(llm_gateway=gateway, prompt_manager=_FakePromptManager())  # type: ignore[arg-type]
    result = await proposer.propose(_ctx(), domain="skill", prompt_version="s2-v1", scene="s2")
    assert len(result) == 2
    assert result[0].display_name == "MySQL"
    assert gateway.calls == 1


@pytest.mark.asyncio
async def test_retry_once_on_invalid_json() -> None:
    gateway = _FakeGateway(
        [
            "not-json",
            '{"candidates":[{"display_name":"Python编程","model_score":0.7}]}',
        ]
    )
    proposer = GenerativeProposer(llm_gateway=gateway, prompt_manager=_FakePromptManager())  # type: ignore[arg-type]
    result = await proposer.propose(_ctx(), domain="skill", prompt_version="s2-v1", scene="s2")
    assert len(result) == 1
    assert gateway.calls == 2


@pytest.mark.asyncio
async def test_raise_need_review_after_retry_fails() -> None:
    gateway = _FakeGateway(["bad", "still-bad"])
    proposer = GenerativeProposer(llm_gateway=gateway, prompt_manager=_FakePromptManager())  # type: ignore[arg-type]
    with pytest.raises(NeedReviewError):
        await proposer.propose(_ctx(), domain="skill", prompt_version="s2-v1", scene="s2")
