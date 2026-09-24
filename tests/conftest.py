"""公共测试夹具。"""

from __future__ import annotations

import pytest

from label_agent.domain.models.content import ContentBundle


@pytest.fixture()
def sample_content_bundle() -> ContentBundle:
    return ContentBundle(
        normalized_text="这是一张复古胶片风格的照片",
        content_hash="sha256:testhash",
    )
