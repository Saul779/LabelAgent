"""LLM Provider 配置装配测试。"""

from __future__ import annotations

from label_agent.bootstrap.inference_factory import build_llm_gateway
from label_agent.inference.providers.azure_openai_provider import AzureOpenAiProvider
from label_agent.inference.providers.base import ModelCompletionRequest
from label_agent.inference.providers.local_vllm_provider import LocalVllmProvider
from label_agent.inference.providers.openai_provider import OpenAiProvider
from label_agent.settings import Settings


def test_gateway_registers_models_with_matching_providers() -> None:
    settings = Settings(
        OPENAI_API_KEY="openai-key",
        OPENAI_BASE_URL="https://openai.example/v1",
        AZURE_OPENAI_API_KEY="azure-key",
        AZURE_OPENAI_ENDPOINT="https://azure.example",
        LOCAL_VLLM_BASE_URL="http://vllm:8000/v1",
    )
    config = {
        "inference": {
            "default_model_alias": "primary",
            "models": [
                {"alias": "primary", "provider": "openai", "model_name": "model-a"},
                {
                    "alias": "fallback",
                    "provider": "azure_openai",
                    "model_name": "deployment-b",
                },
                {"alias": "local", "provider": "local_vllm", "model_name": "model-c"},
            ],
        }
    }

    gateway = build_llm_gateway("openai-key", config, settings=settings)

    registry = gateway._model_registry
    assert isinstance(registry.resolve("primary").provider, OpenAiProvider)
    assert isinstance(registry.resolve("fallback").provider, AzureOpenAiProvider)
    assert isinstance(registry.resolve("local").provider, LocalVllmProvider)
    assert registry.resolve("fallback").model_name == "deployment-b"


def test_azure_payload_uses_deployment_url_without_model_body() -> None:
    provider = AzureOpenAiProvider(
        api_key="azure-key",
        endpoint="https://azure.example/",
    )
    request = ModelCompletionRequest(system_prompt="system", user_prompt="user")
    payload = provider._build_payload("deployment/name", request)

    assert "model" not in payload
    assert provider._request_url("deployment/name").endswith(
        "/openai/deployments/deployment%2Fname/chat/completions"
    )
