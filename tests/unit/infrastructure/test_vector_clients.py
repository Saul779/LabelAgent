"""Tag Service 状态回写与 Milvus 代理 HTTP 客户端测试。"""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from label_agent.domain.models.tag import VectorState
from label_agent.infrastructure.milvus_proxy.client import MilvusProxyClient
from label_agent.infrastructure.tag_service.http_client import TagServiceHttpClient
from label_agent.settings import Settings

_TAG_PAYLOAD = {
    "tag_id": "tag-1",
    "canonical_tag_id": "tag-1",
    "display_name": "清晨观云",
    "name_type": "standard",
    "domain": "content",
    "lifecycle_status": "ACTIVE",
    "vector_state": "READY",
    "tag_definition_version": 1,
    "embedding_space_id": "text-v1",
}


@pytest.mark.asyncio
@respx.mock
async def test_tag_service_updates_vector_state_with_version_guard() -> None:
    route = respx.patch("http://tag-service/v1/tags/tag-1/vector-state").mock(
        return_value=Response(200, json=_TAG_PAYLOAD)
    )
    client = TagServiceHttpClient("http://tag-service", 1000)

    result = await client.update_vector_state(
        "tag-1",
        VectorState.READY,
        expected_definition_version=1,
    )

    assert result.vector_state == VectorState.READY
    assert route.calls.last.request.content


@pytest.mark.asyncio
@respx.mock
async def test_tag_service_sends_bearer_token_when_configured() -> None:
    route = respx.get("http://tag-service/v1/tags/search").mock(
        return_value=Response(200, json=[])
    )
    client = TagServiceHttpClient("http://tag-service", 1000, auth_token="secret-token")

    await client.search_tags("PMP", "certificate")

    assert route.calls.last.request.headers["Authorization"] == "Bearer secret-token"


@pytest.mark.asyncio
@respx.mock
async def test_milvus_proxy_upsert_uses_expected_contract() -> None:
    route = respx.post("http://milvus-proxy/v1/vectors/upsert").mock(return_value=Response(204))
    settings = Settings(
        MILVUS_PROXY_BASE_URL="http://milvus-proxy",
        MILVUS_PROXY_TIMEOUT_MS=1000,
    )
    client = MilvusProxyClient(settings)

    await client.upsert(
        "tag_vectors",
        ["tag-1:1:text-v1"],
        [[1.0, 0.0]],
        [{"tag_id": "tag-1"}],
    )

    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_milvus_proxy_search_uses_shared_vector_contract() -> None:
    route = respx.post("http://milvus-proxy/v1/vectors/search").mock(
        return_value=Response(200, json=[{"id": "category-fruit", "score": 0.95}])
    )
    settings = Settings(
        MILVUS_PROXY_BASE_URL="http://milvus-proxy",
        MILVUS_PROXY_TIMEOUT_MS=1000,
    )
    client = MilvusProxyClient(settings)

    hits = await client.search(
        "product_category_vectors",
        [1.0, 0.0],
        20,
        {"level": 2, "taxonomy_version": "taxonomy-v1"},
    )

    assert hits[0]["id"] == "category-fruit"
    assert route.calls.last.request.content
