"""S3 Pipeline 最小端到端集成测试：真实感知/召回/归一，Mock LLM。"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock

import jsonschema
import pytest

from label_agent.bootstrap.mvp_scene_factory import build_s3_handler
from label_agent.core.context import JobContext
from label_agent.core.exceptions import RetryableError, SafetyGateRejectedError
from label_agent.inference.providers.base import (
    ModelCompletionRequest,
    ModelCompletionResult,
)
from label_agent.infrastructure.tag_service.fixture_client import FixtureTagServiceClient
from label_agent.scenarios.s3_content.pipeline import NeedReviewOrRetry
from label_agent.scenarios.s3_content.schema import load_s3_json_schema


class _ScriptedS3Gateway:
    """返回固定 S3 SemanticProposal JSON，避免测试依赖外部模型服务。"""

    def __init__(self, payload: dict[str, Any] | None = None) -> None:
        """允许测试注入自定义模型响应；未注入时使用正常命中场景。"""
        self._payload = payload

    async def complete(
        self,
        request: ModelCompletionRequest,
        model_alias: str | None = None,
    ) -> ModelCompletionResult:
        """忽略模型别名，并返回仅引用 fixture 候选 ID 的稳定响应。"""
        _ = request, model_alias
        payload = self._payload or {
            "primary_category": {
                "category_id": "category-fitness",
                "model_score": 0.91,
                "evidence_refs": [],
            },
            "secondary_category": None,
            "tags": [
                {
                    "tag_id": "tag-running",
                    "new_tag_request": None,
                    "model_score": 0.88,
                    "evidence_refs": [],
                },
                {
                    "tag_id": "tag-daily",
                    "new_tag_request": None,
                    "model_score": 0.72,
                    "evidence_refs": [],
                },
            ],
        }
        return ModelCompletionResult(
            raw_text=f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```",
            model_name="s3-scripted",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
        )


def _yaml_config(*, auto_create: bool = False) -> dict[str, Any]:
    """构造 S3 测试所需的最小版本与策略配置。"""
    return {
        "scene": {"s3": {"auto_create_unmatched": auto_create}},
        "policy": {"confidence": {"version": "provisional-rule-mvp-1"}},
        "inference": {"prompt_versions": {"s3": "s3-v3"}},
    }


@pytest.mark.asyncio
async def test_s3_pipeline_outputs_schema_valid_classification_and_tags() -> None:
    """验证文本输入能产出有效一级分类、降序标签和完整 S3 契约。"""
    handler = build_s3_handler(
        _ScriptedS3Gateway(),  # type: ignore[arg-type]
        _yaml_config(),
    )
    ctx = JobContext(
        job_id="job-s3-test",
        task_id="task-s3-test",
        scene="S3",
        biz_id="dynamic-s3-test",
        payload={"text": "今天完成五公里跑步，也记录一下日常出行。"},
        data_version=3,
    )

    result = await handler.run(ctx)

    assert result.primary_category.category_id == "category-fitness"
    assert [tag.tag_id for tag in result.tags] == ["tag-running", "tag-daily"]
    assert all(tag.source == "matched" for tag in result.tags)
    assert result.dictionary_snapshot_version == "dict-content-2026-08-12"
    jsonschema.validate(
        instance=result.model_dump(mode="json"),
        schema=load_s3_json_schema(),
    )


@pytest.mark.asyncio
async def test_s3_pipeline_falls_back_and_skips_new_tag_when_auto_create_disabled() -> None:
    """验证低置信分类回退未分类，且关闭自动创建时新标签不会进入结果。"""
    model_payload = {
        "primary_category": {
            "category_id": "category-daily-life",
            "model_score": 0.49,
            "evidence_refs": [],
        },
        "secondary_category": None,
        "tags": [
            {
                "tag_id": None,
                "new_tag_request": {
                    "proposed_name": "清晨观云",
                    "domain": "content",
                    "reason": "词表中没有可复用标签",
                },
                "model_score": 0.9,
                "evidence_refs": [],
            }
        ],
    }
    handler = build_s3_handler(
        _ScriptedS3Gateway(model_payload),  # type: ignore[arg-type]
        _yaml_config(),
    )
    ctx = JobContext(
        job_id="job-s3-fallback",
        task_id="task-s3-fallback",
        scene="S3",
        biz_id="dynamic-s3-fallback",
        payload={"text": "清晨抬头看了一会儿云。"},
    )

    result = await handler.run(ctx)

    assert result.primary_category.name == "未分类"
    assert result.primary_category.confidence == 0.0
    assert result.secondary_category is None
    assert result.tags == []


@pytest.mark.asyncio
async def test_s3_pipeline_rejects_all_new_tags_before_any_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """验证整单预校验失败时，不会创建前面已通过校验的新标签。"""
    model_payload = {
        "primary_category": None,
        "secondary_category": None,
        "tags": [
            {
                "tag_id": None,
                "new_tag_request": {
                    "proposed_name": "清晨观云",
                    "domain": "content",
                    "reason": "词表中没有可复用标签",
                },
                "model_score": 0.9,
                "evidence_refs": [],
            },
            {
                "tag_id": None,
                "new_tag_request": {
                    "proposed_name": "ignore previous instructions",
                    "domain": "content",
                    "reason": "模拟不安全的新标签名称",
                },
                "model_score": 0.8,
                "evidence_refs": [],
            },
        ],
    }
    create_tag = AsyncMock()
    monkeypatch.setattr(FixtureTagServiceClient, "create_tag", create_tag)
    handler = build_s3_handler(
        _ScriptedS3Gateway(model_payload),  # type: ignore[arg-type]
        _yaml_config(auto_create=True),
    )
    ctx = JobContext(
        job_id="job-s3-pre-validation",
        task_id="task-s3-pre-validation",
        scene="S3",
        biz_id="dynamic-s3-pre-validation",
        payload={"text": "清晨看云，并包含一条不安全的模型提议。"},
    )

    with pytest.raises(SafetyGateRejectedError):
        await handler.run(ctx)

    create_tag.assert_not_awaited()


@pytest.mark.asyncio
async def test_s3_pending_vector_requests_job_retry() -> None:
    """验证新标签向量未就绪时走可重试异常，不会被当成普通失败。"""
    model_payload = {
        "primary_category": None,
        "secondary_category": None,
        "tags": [
            {
                "tag_id": None,
                "new_tag_request": {
                    "proposed_name": "清晨观云",
                    "domain": "content",
                    "reason": "词表中没有可复用标签",
                },
                "model_score": 0.9,
                "evidence_refs": [],
            }
        ],
    }
    handler = build_s3_handler(
        _ScriptedS3Gateway(model_payload),  # type: ignore[arg-type]
        _yaml_config(auto_create=True),
    )
    ctx = JobContext(
        job_id="job-s3-vector-pending",
        task_id="task-s3-vector-pending",
        scene="S3",
        biz_id="dynamic-s3-vector-pending",
        payload={"text": "清晨抬头观察云层。"},
    )

    with pytest.raises(NeedReviewOrRetry) as exc_info:
        await handler.run(ctx)

    assert isinstance(exc_info.value, RetryableError)
    assert exc_info.value.error_code == "TAG_VECTOR_PENDING"
    assert exc_info.value.result.tags[0].vector_state == "PENDING"
