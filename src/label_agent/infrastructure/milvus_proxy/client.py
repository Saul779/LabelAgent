"""MilvusProxyClient：标签向量/用户向量/RAG 知识向量的统一访问入口（按 collection 隔离）。"""

from __future__ import annotations

import httpx

from label_agent.core.exceptions import NonRetryableError, RetryableError
from label_agent.settings import Settings


class MilvusProxyClient:
    """Milvus 代理客户端：向量写入与检索。"""

    def __init__(self, settings: Settings) -> None:
        """注入代理服务地址等配置。"""
        self._client = httpx.AsyncClient(
            base_url=settings.milvus_proxy_base_url,
            timeout=settings.milvus_proxy_timeout_ms / 1000,
        )

    async def upsert(
        self,
        collection: str,
        ids: list[str],
        vectors: list[list[float]],
        metadata: list[dict],
    ) -> None:
        """通过代理幂等写入向量。"""
        if not (len(ids) == len(vectors) == len(metadata)):
            raise ValueError("向量 ids/vectors/metadata 数量必须一致")
        await self._request(
            "POST",
            "/v1/vectors/upsert",
            json={
                "collection": collection,
                "ids": ids,
                "vectors": vectors,
                "metadata": metadata,
            },
        )

    async def search(
        self,
        collection: str,
        query_vector: list[float],
        top_k: int,
        filters: dict,
    ) -> list[dict]:
        """通过代理执行 ANN 检索。"""
        response = await self._request(
            "POST",
            "/v1/vectors/search",
            json={
                "collection": collection,
                "query_vector": query_vector,
                "top_k": top_k,
                "filters": filters,
            },
        )
        payload = response.json()
        if not isinstance(payload, list):
            raise NonRetryableError("Milvus 代理检索响应必须为数组")
        return payload

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict,
    ) -> httpx.Response:
        """统一执行代理请求并分类异常。"""
        try:
            response = await self._client.request(method, path, json=json)
        except httpx.RequestError as exc:
            raise RetryableError(f"Milvus 代理网络异常: {exc}") from exc
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableError(f"Milvus 代理可重试状态码: {response.status_code}")
        if response.is_error:
            raise NonRetryableError(
                f"Milvus 代理请求失败: status={response.status_code} body={response.text[:300]}"
            )
        return response
