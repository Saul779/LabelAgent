"""SemanticProposer：产出 SemanticProposal（§5.1.5）。

模型只能引用候选 ID，不得自行生成 ID；出参在此层解析为结构化
SemanticProposal 后立即交给 EntityResolver，不做任何写操作。
"""

from __future__ import annotations

import json
import uuid

from pydantic import ValidationError

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NeedReviewError
from label_agent.domain.models.proposal import SemanticProposal
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.inference.providers.base import ModelCompletionRequest


class SemanticProposer:
    """S3 语义提议器：在候选集约束下由 LLM 提出类目/标签建议。"""

    def __init__(
        self,
        llm_gateway: LlmGateway,
        prompt_manager: PromptManager,
        prompt_version: str,
    ) -> None:
        """注入 LLM 网关与 Prompt 管理器。"""
        self._llm_gateway = llm_gateway
        self._prompt_manager = prompt_manager
        self._prompt_version = prompt_version

    async def propose(self, ctx: JobContext) -> SemanticProposal:
        """基于 ContentBundle 与候选集生成 SemanticProposal。"""
        category_candidates = [
            candidate.model_dump(mode="json") for candidate in ctx.category_candidates
        ]
        tag_candidates = [candidate.model_dump(mode="json") for candidate in ctx.candidates]
        system_prompt, user_prompt = self._prompt_manager.render(
            scene=ctx.scene,
            prompt_version=self._prompt_version,
            variables={
                "category_candidates": json.dumps(category_candidates, ensure_ascii=False),
                "tag_candidates": json.dumps(tag_candidates, ensure_ascii=False),
                "normalized_text": ctx.content_bundle.normalized_text if ctx.content_bundle else "",
            },
        )
        request = ModelCompletionRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema=SemanticProposal.model_json_schema(),
        )
        result = await self._llm_gateway.complete(request)
        proposal = self._parse(result.raw_text)
        ctx.model_run_id = proposal.model_run_id
        ctx.prompt_version = proposal.prompt_version
        return proposal

    def _parse(self, raw_text: str) -> SemanticProposal:
        """解析可能带 Markdown 围栏的模型 JSON，失败统一转为待人工复核错误。"""
        try:
            payload = json.loads(_extract_json_object(raw_text))
            if not isinstance(payload, dict):
                raise TypeError("模型输出顶层必须是 JSON 对象")
            payload.setdefault("model_run_id", f"run-{uuid.uuid4().hex[:12]}")
            payload.setdefault("prompt_version", self._prompt_version)
            return SemanticProposal.model_validate(payload)
        except (json.JSONDecodeError, TypeError, ValueError, ValidationError) as exc:
            raise NeedReviewError(f"S3 模型输出无法解析为 SemanticProposal: {exc}") from exc


def _extract_json_object(raw_text: str) -> str:
    """从纯 JSON 或 Markdown 代码围栏文本中提取最外层 JSON 对象。"""
    text = raw_text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("模型输出中未找到 JSON 对象")
    return text[start : end + 1]
