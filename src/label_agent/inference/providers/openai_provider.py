"""OpenAI Provider 适配：文本 / 多模态、JSON Mode、超时与基础重试。"""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from label_agent.core.exceptions import NonRetryableError, RetryableError
from label_agent.inference.providers.base import ModelCompletionRequest, ModelCompletionResult

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_MAX_ATTEMPTS = 3


class OpenAiProvider:
    """OpenAI Chat Completions 适配器，供 LlmGateway 实际发请求。"""

    provider_name = "openai"

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_sec: float = 60.0,
    ) -> None:
        """配置 API Key、Base URL 等连接参数。"""
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec

    async def complete(
        self,
        model_name: str,
        request: ModelCompletionRequest,
    ) -> ModelCompletionResult:
        """向 OpenAI 发送补全请求并返回统一结果。"""
        payload = self._build_payload(model_name, request)
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            started = time.perf_counter()
            try:
                async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                    response = await client.post(
                        self._request_url(model_name),
                        headers=self._request_headers(),
                        params=self._request_params(),
                        json=payload,
                    )
                latency_ms = int((time.perf_counter() - started) * 1000)
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise RetryableError(f"OpenAI 可重试状态码: {response.status_code}")
                if response.status_code >= 400:
                    raise NonRetryableError(
                        f"OpenAI 调用失败: {response.status_code} {response.text[:500]}"
                    )
                body = response.json()
                return self._parse_response(body, model_name, latency_ms)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = RetryableError(f"OpenAI 网络异常: {exc}")
                logger.warning("OpenAI complete 重试 %s/%s: %s", attempt, _MAX_ATTEMPTS, exc)
            except RetryableError as exc:
                last_error = exc
                logger.warning("OpenAI complete 重试 %s/%s: %s", attempt, _MAX_ATTEMPTS, exc)
        assert last_error is not None
        raise last_error

    def _request_url(self, model_name: str) -> str:
        """返回补全接口地址，供兼容 Provider 覆盖。"""
        return f"{self._base_url}/chat/completions"

    def _request_headers(self) -> dict[str, str]:
        """返回请求头，供不同鉴权协议覆盖。"""
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _request_params(self) -> dict[str, str] | None:
        """返回请求查询参数。"""
        return None

    def _build_payload(self, model_name: str, request: ModelCompletionRequest) -> dict[str, Any]:
        """将内部请求结构转为 OpenAI API payload（支持多模态）。"""
        user_content: str | list[dict[str, Any]]
        if request.image_urls:
            parts: list[dict[str, Any]] = [{"type": "text", "text": request.user_prompt}]
            for url in request.image_urls:
                parts.append({"type": "image_url", "image_url": {"url": url}})
            user_content = parts
        else:
            user_content = request.user_prompt

        payload: dict[str, Any] = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": request.system_prompt},
                {"role": "user", "content": user_content},
            ],
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
        }
        if request.response_schema is not None:
            payload["response_format"] = {"type": "json_object"}
        return payload

    @staticmethod
    def _parse_response(
        body: dict[str, Any],
        model_name: str,
        latency_ms: int,
    ) -> ModelCompletionResult:
        """解析 OpenAI 响应为 ModelCompletionResult。"""
        choices = body.get("choices") or []
        if not choices:
            raise NonRetryableError("OpenAI 响应缺少 choices")
        message = choices[0].get("message") or {}
        raw_text = message.get("content") or ""
        usage = body.get("usage") or {}
        return ModelCompletionResult(
            raw_text=raw_text,
            model_name=body.get("model") or model_name,
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            completion_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=latency_ms,
        )
