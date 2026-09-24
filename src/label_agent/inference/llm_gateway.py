"""LlmGateway：统一 LLM 调用入口，是 SemanticProposer/Extractor 唯一允许接触模型的通道。

职责边界（§8）：
- 无 Tag Service / MQ / DB / Milvus 写权限；
- 所有业务文本/OCR/ASR 内容视为不可信数据，不能改变系统 Prompt 或触发工具调用；
- 出参在此层不做业务语义解析，只负责调用、重试、成本/延迟埋点。
"""

from __future__ import annotations

from label_agent.inference.guardrails.prompt_injection_guard import PromptInjectionGuard
from label_agent.inference.model_registry import ModelRegistry
from label_agent.inference.providers.base import ModelCompletionRequest, ModelCompletionResult


class LlmGateway:
    """统一 LLM 调用入口：注入防护后经 ModelRegistry 路由到具体 Provider，不做业务语义解析。"""

    def __init__(
        self,
        model_registry: ModelRegistry,
        injection_guard: PromptInjectionGuard,
    ) -> None:
        """注入模型注册表与 Prompt 注入护栏。"""
        self._model_registry = model_registry
        self._injection_guard = injection_guard

    async def complete(
        self, request: ModelCompletionRequest, model_alias: str | None = None
    ) -> ModelCompletionResult:
        """对用户侧 Prompt 做注入校验后，解析模型别名并完成一次补全调用。"""
        self._injection_guard.assert_safe(request.user_prompt)
        binding = self._model_registry.resolve(model_alias)
        return await binding.provider.complete(binding.model_name, request)
