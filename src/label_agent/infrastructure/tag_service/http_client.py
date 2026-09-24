"""Tag Service 独立部署形态下的 HTTP 客户端实现（standalone_http，D007）。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from label_agent.core.exceptions import NonRetryableError, RetryableError
from label_agent.domain.models.candidate import CategoryCandidate, TagCandidate
from label_agent.domain.models.tag import Tag, VectorState


class TagServiceHttpClient:
    """TagServiceClient 的 HTTP 实现：适用于 Tag Service 独立部署（standalone_http）形态。"""

    def __init__(
        self,
        base_url: str,
        timeout_ms: int,
        auth_token: str | None = None,
    ) -> None:
        """按 base_url/timeout 初始化底层 HTTP 客户端。"""
        headers = {"Authorization": f"Bearer {auth_token}"} if auth_token else None
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_ms / 1000,
            headers=headers,
        )

    async def search_tags(self, query: str, domain: str) -> list[TagCandidate]:
        response = await self._request(
            "GET",
            "/v1/tags/search",
            params={"query": query, "domain": domain},
        )
        return [TagCandidate.model_validate(item) for item in response.json()]

    async def search_categories(self, domain: str) -> list[CategoryCandidate]:
        response = await self._request("GET", "/v1/categories", params={"domain": domain})
        return [CategoryCandidate.model_validate(item) for item in response.json()]

    async def create_tag(self, proposed_name: str, domain: str, idempotency_key: str) -> Tag:
        response = await self._request(
            "POST",
            "/v1/tags",
            json={"proposed_name": proposed_name, "domain": domain},
            headers={"Idempotency-Key": idempotency_key},
        )
        return Tag.model_validate(response.json())

    async def get_tag(self, tag_id: str) -> Tag | None:
        response = await self._request("GET", f"/v1/tags/{tag_id}", allow_not_found=True)
        return None if response.status_code == 404 else Tag.model_validate(response.json())

    async def update_vector_state(
        self,
        tag_id: str,
        vector_state: VectorState,
        *,
        expected_definition_version: int,
    ) -> Tag:
        response = await self._request(
            "PATCH",
            f"/v1/tags/{tag_id}/vector-state",
            json={
                "vector_state": vector_state.value,
                "expected_definition_version": expected_definition_version,
            },
        )
        return Tag.model_validate(response.json())

    async def list_tags_by_vector_state(
        self,
        vector_state: VectorState,
        *,
        limit: int,
    ) -> list[Tag]:
        response = await self._request(
            "GET",
            "/v1/tags",
            params={"vector_state": vector_state.value, "limit": limit},
        )
        return [Tag.model_validate(item) for item in response.json()]

    async def _request(
        self,
        method: str,
        path: str,
        *,
        allow_not_found: bool = False,
        params: Mapping[str, str | int | float | bool | None] | None = None,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> httpx.Response:
        """统一执行请求并将状态码映射为可重试语义。"""
        try:
            response = await self._client.request(
                method,
                path,
                params=params,
                json=json,
                headers=headers,
            )
        except httpx.RequestError as exc:
            raise RetryableError(f"Tag Service 网络异常: {exc}") from exc
        if allow_not_found and response.status_code == 404:
            return response
        if response.status_code == 429 or response.status_code >= 500:
            raise RetryableError(f"Tag Service 可重试状态码: {response.status_code}")
        if response.is_error:
            raise NonRetryableError(
                f"Tag Service 请求失败: status={response.status_code} body={response.text[:300]}"
            )
        return response
