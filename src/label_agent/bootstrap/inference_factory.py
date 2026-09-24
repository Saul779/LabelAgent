"""场景无关的 LLM/Embedding MVP 装配。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from label_agent.inference.embeddings.openai_embedding_provider import OpenAiEmbeddingProvider
from label_agent.inference.guardrails.prompt_injection_guard import PromptInjectionGuard
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.model_registry import ModelBinding, ModelRegistry
from label_agent.inference.providers.azure_openai_provider import AzureOpenAiProvider
from label_agent.inference.providers.base import ModelProvider
from label_agent.inference.providers.local_vllm_provider import LocalVllmProvider
from label_agent.inference.providers.openai_provider import OpenAiProvider
from label_agent.settings import Settings, get_settings

REPO_ROOT = Path(__file__).resolve().parents[3]

load_dotenv(REPO_ROOT / ".env")


def load_yaml_config(env: str | None = None) -> dict[str, Any]:
    """加载 base + 环境覆盖 YAML 配置。"""
    from label_agent.settings import _load_yaml_layer

    app_env = env or os.getenv("APP_ENV") or "dev"
    return _load_yaml_layer(app_env)


def require_openai_api_key(settings: Settings | None = None) -> str:
    """读取 OPENAI_API_KEY，缺失时给出明确错误。"""
    current_settings = settings or get_settings()
    api_key = (current_settings.openai_api_key or "").strip()
    if not api_key:
        raise RuntimeError("请设置环境变量 OPENAI_API_KEY")
    return api_key


def build_llm_gateway(
    api_key: str,
    yaml_config: dict[str, Any],
    *,
    settings: Settings | None = None,
) -> LlmGateway:
    """按模型配置注册对应 Provider；不可用的非默认 Provider 会被跳过。"""
    inference = yaml_config.get("inference") or {}
    default_alias = str(inference.get("default_model_alias") or "primary")
    models = inference.get("models") or []
    current_settings = settings or get_settings()
    registry = ModelRegistry(default_alias=default_alias)
    registered: set[str] = set()
    providers: dict[str, ModelProvider] = {}

    for model in models:
        provider_name = str(model.get("provider") or "").strip()
        alias = str(model.get("alias") or "").strip()
        model_name = str(model.get("model_name") or "").strip()
        if not provider_name or not alias or not model_name:
            continue

        provider = providers.get(provider_name)
        if provider is None:
            provider = _build_provider(provider_name, current_settings, api_key)
            if provider is None:
                if alias == default_alias:
                    raise RuntimeError(f"默认模型 {alias} 的 Provider {provider_name} 配置不完整")
                continue
            providers[provider_name] = provider

        registry.register(ModelBinding(alias=alias, provider=provider, model_name=model_name))
        registered.add(alias)

    if default_alias not in registered:
        raise RuntimeError(f"默认模型 alias 未注册: {default_alias}")
    return LlmGateway(
        model_registry=registry,
        injection_guard=PromptInjectionGuard(banned_patterns=[]),
    )


def _build_provider(
    provider_name: str,
    settings: Settings,
    openai_api_key: str,
) -> ModelProvider | None:
    """创建 Provider；可选 Provider 缺少凭据时返回 None。"""
    if provider_name == "openai":
        return OpenAiProvider(api_key=openai_api_key, base_url=settings.openai_base_url)
    if provider_name == "azure_openai":
        if not settings.azure_openai_api_key or not settings.azure_openai_endpoint:
            return None
        return AzureOpenAiProvider(
            api_key=settings.azure_openai_api_key,
            endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )
    if provider_name == "local_vllm":
        return LocalVllmProvider(base_url=settings.local_vllm_base_url)
    raise ValueError(f"不支持的模型 Provider: {provider_name}")


def build_embedding_provider(
    api_key: str,
    *,
    settings: Settings | None = None,
) -> OpenAiEmbeddingProvider:
    """装配商品/职业/证书词表共用的 Embedding Provider。"""
    current_settings = settings or get_settings()
    return OpenAiEmbeddingProvider(
        api_key=api_key,
        model_name=current_settings.openai_embedding_model,
        base_url=current_settings.openai_base_url,
    )
