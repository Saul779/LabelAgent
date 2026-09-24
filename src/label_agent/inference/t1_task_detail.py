"""T1 自动分支判断与结构化字段提取。"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NeedReviewError
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.inference.providers.base import ModelCompletionRequest

logger = logging.getLogger(__name__)

BizTaskType = Literal["relationship", "skill", "dessert"]
_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class T1ClassificationProposal(_StrictModel):
    """模型对任务业务分支的唯一判断。"""

    biz_task_type: BizTaskType


class T1ExtractionProposal(_StrictModel):
    """模型提取的原始字段；最终业务校验由各分支 Extractor 完成。"""

    relation_target: Literal["person", "other_object"] | None = None
    relation_target_detail: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    service_mode: Literal["offline", "non_offline"] | None = None
    ambiguity_codes: list[Literal["AMBIGUOUS_RELATION_TARGET", "AMBIGUOUS_SERVICE_MODE"]] = Field(
        default_factory=list
    )


class T1TaskDetailInference:
    """先判断 relationship/skill/兜底类，再按所选分支提取字段。"""

    def __init__(
        self,
        llm_gateway: LlmGateway,
        prompt_manager: PromptManager,
        *,
        classify_prompt_version: str = "t1-classify-v1",
        extract_prompt_version: str = "t1-v1",
    ) -> None:
        self._llm_gateway = llm_gateway
        self._prompt_manager = prompt_manager
        self._classify_prompt_version = classify_prompt_version
        self._extract_prompt_version = extract_prompt_version

    async def classify(self, ctx: JobContext) -> BizTaskType:
        """由模型在三个业务分支中选择且只选择一个。"""
        normalized_text = _normalized_text(ctx)
        system_prompt, user_prompt = self._prompt_manager.render(
            scene="t1",
            prompt_version=self._classify_prompt_version,
            variables={"normalized_text": normalized_text},
        )
        proposal = await self._complete_and_parse(
            system_prompt,
            user_prompt,
            T1ClassificationProposal,
            error_context="T1 任务类型判断",
        )
        return proposal.biz_task_type

    async def extract(self, ctx: JobContext, biz_task_type: BizTaskType) -> T1ExtractionProposal:
        """按已判断的业务分支提取对应字段。"""
        normalized_text = _normalized_text(ctx)
        system_prompt, user_prompt = self._prompt_manager.render(
            scene="t1",
            prompt_version=self._extract_prompt_version,
            variables={
                "biz_task_type": biz_task_type,
                "normalized_text": normalized_text,
            },
        )
        proposal = await self._complete_and_parse(
            system_prompt,
            user_prompt,
            T1ExtractionProposal,
            error_context=f"T1 {biz_task_type} 字段提取",
        )
        ctx.prompt_version = self._extract_prompt_version
        return proposal

    async def _complete_and_parse(self, system_prompt, user_prompt, model_cls, *, error_context):
        request = ModelCompletionRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=model_cls.model_json_schema(),
            temperature=0.0,
            max_tokens=1024,
        )
        result = await self._llm_gateway.complete(request)
        try:
            return _parse_model(result.raw_text, model_cls)
        except (json.JSONDecodeError, ValueError, TypeError, ValidationError) as first_error:
            logger.warning("%s输出解析失败，重试一次: %s", error_context, first_error)
            retry_request = request.model_copy(
                update={
                    "system_prompt": system_prompt
                    + "\n上次输出无法通过 Schema 校验。请只输出一个合法 JSON 对象。"
                }
            )
            retry_result = await self._llm_gateway.complete(retry_request)
            try:
                return _parse_model(retry_result.raw_text, model_cls)
            except (json.JSONDecodeError, ValueError, TypeError, ValidationError) as exc:
                raise NeedReviewError(f"{error_context}输出无法解析: {exc}") from exc


def _normalized_text(ctx: JobContext) -> str:
    if ctx.content_bundle is None or not ctx.content_bundle.normalized_text.strip():
        raise ValueError("T1 推理缺少规整后的任务文本")
    return ctx.content_bundle.normalized_text


def _parse_model(raw_text: str, model_cls):
    text = (raw_text or "").strip()
    match = _JSON_FENCE.search(text)
    if match:
        text = match.group(1).strip()
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise TypeError("模型输出顶层必须是 JSON 对象")
    return model_cls.model_validate(payload)
