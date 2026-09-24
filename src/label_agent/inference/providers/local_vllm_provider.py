"""自建 vLLM 推理服务 Provider 适配，用于成本敏感场景或私有化部署。"""

from __future__ import annotations

from label_agent.inference.providers.openai_provider import OpenAiProvider


class LocalVllmProvider(OpenAiProvider):
    """基于 vLLM OpenAI-compatible API 的 Provider。"""

    provider_name = "local_vllm"

    def __init__(self, base_url: str, api_key: str = "not-required") -> None:
        """注入本地推理服务地址；默认不要求鉴权。"""
        super().__init__(api_key=api_key, base_url=base_url)
