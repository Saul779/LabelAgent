"""Azure OpenAI Provider 适配（作为多模型切换中的 fallback，见 configs/base.yaml）。"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from label_agent.inference.providers.base import ModelCompletionRequest
from label_agent.inference.providers.openai_provider import OpenAiProvider


class AzureOpenAiProvider(OpenAiProvider):
    """Azure OpenAI Chat Completions 适配器。"""

    provider_name = "azure_openai"

    def __init__(self, api_key: str, endpoint: str, api_version: str = "2024-06-01") -> None:
        """注入 Azure 资源端点、密钥与 API 版本。"""
        super().__init__(api_key=api_key, base_url=endpoint)
        self._api_version = api_version

    def _request_url(self, model_name: str) -> str:
        deployment = quote(model_name, safe="")
        return f"{self._base_url}/openai/deployments/{deployment}/chat/completions"

    def _request_headers(self) -> dict[str, str]:
        return {"api-key": self._api_key, "Content-Type": "application/json"}

    def _request_params(self) -> dict[str, str]:
        return {"api-version": self._api_version}

    def _build_payload(
        self,
        model_name: str,
        request: ModelCompletionRequest,
    ) -> dict[str, Any]:
        """Azure 由 URL 中的 deployment 选模型，请求体不发送 model。"""
        payload = super()._build_payload(model_name, request)
        payload.pop("model", None)
        return payload
