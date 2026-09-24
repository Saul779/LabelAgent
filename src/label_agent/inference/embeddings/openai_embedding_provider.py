"""OpenAI Embedding Provider（默认 text-embedding-3-small）。"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from label_agent.core.exceptions import NonRetryableError, RetryableError

logger = logging.getLogger(__name__)

_DEFAULT_BASE_URL = "https://api.openai.com/v1"
_DEFAULT_MODEL = "text-embedding-3-small"
_MAX_ATTEMPTS = 3
_BATCH_SIZE = 10


class OpenAiEmbeddingProvider:
    """OpenAI Embedding API 适配，为词表索引与相似度检索提供向量。"""

    def __init__(
        self,
        api_key: str,
        *,
        model_name: str = _DEFAULT_MODEL,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_sec: float = 60.0,
    ) -> None:
        """配置 API Key、模型名与 Base URL。"""
        self._api_key = api_key
        self._model_name = model_name
        self._base_url = base_url.rstrip("/")
        self._timeout_sec = timeout_sec

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """对文本列表批量生成向量，超长则分批请求。"""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), _BATCH_SIZE):
            batch = texts[start : start + _BATCH_SIZE]
            vectors.extend(await self._embed_batch(batch))
        return vectors

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        """单批调用 Embedding API。"""
        payload = {"model": self._model_name, "input": texts}
        last_error: Exception | None = None
        for attempt in range(1, _MAX_ATTEMPTS + 1):
            try:
                async with httpx.AsyncClient(timeout=self._timeout_sec) as client:
                    response = await client.post(
                        f"{self._base_url}/embeddings",
                        headers={
                            "Authorization": f"Bearer {self._api_key}",
                            "Content-Type": "application/json",
                        },
                        json=payload,
                    )
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise RetryableError(f"Embedding 可重试状态码: {response.status_code}")
                if response.status_code >= 400:
                    raise NonRetryableError(
                        f"Embedding 调用失败: {response.status_code} {response.text[:500]}"
                    )
                return self._parse_response(response.json(), expected=len(texts))
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_error = RetryableError(f"Embedding 网络异常: {exc}")
                logger.warning("Embedding 重试 %s/%s: %s", attempt, _MAX_ATTEMPTS, exc)
            except RetryableError as exc:
                last_error = exc
                logger.warning("Embedding 重试 %s/%s: %s", attempt, _MAX_ATTEMPTS, exc)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _parse_response(body: dict[str, Any], *, expected: int) -> list[list[float]]:
        """解析 Embedding API 响应为向量列表。"""
        data = body.get("data") or []
        if len(data) != expected:
            raise NonRetryableError(f"Embedding 返回数量不匹配: expect={expected} got={len(data)}")
        ordered = sorted(data, key=lambda item: int(item.get("index", 0)))
        return [list(map(float, item["embedding"])) for item in ordered]
