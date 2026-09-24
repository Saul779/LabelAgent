"""MockTagServiceClient 并发创建冲突后回读已有标签，不重复创建（§6.2）。"""

from __future__ import annotations

import pytest

from label_agent.infrastructure.tag_service.mock_client import MockTagServiceClient


@pytest.mark.asyncio
async def test_create_tag_is_idempotent_by_key() -> None:
    client = MockTagServiceClient()
    first = await client.create_tag("复古胶片风", domain="content", idempotency_key="k1")
    second = await client.create_tag("复古胶片风", domain="content", idempotency_key="k1")

    assert first.tag_id == second.tag_id
    fetched = await client.get_tag(first.tag_id)
    assert fetched is not None
