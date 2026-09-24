"""TagServiceClient：唯一的标签读写接口定义（§6.2、D007）。

分类只读、标签可建（§1 设计原则 7）：本客户端只暴露标签创建接口，
不提供任何分类创建方法。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from label_agent.domain.models.candidate import CategoryCandidate, TagCandidate
from label_agent.domain.models.tag import Tag, VectorState

if TYPE_CHECKING:
    from label_agent.settings import Settings


class TagServiceClient(Protocol):
    """Tag Service 客户端协议/基类。"""

    async def search_tags(self, query: str, domain: str) -> list[TagCandidate]:
        """按查询文本与领域检索标签候选。"""
        ...

    async def search_categories(self, domain: str) -> list[CategoryCandidate]:
        """读取指定领域的分类候选。"""
        ...

    async def create_tag(
        self,
        proposed_name: str,
        domain: str,
        idempotency_key: str,
    ) -> Tag:
        """按幂等键创建标准标签。"""
        ...

    async def get_tag(self, tag_id: str) -> Tag | None:
        """按稳定标签 ID 查询标签实体。"""
        ...

    async def update_vector_state(
        self,
        tag_id: str,
        vector_state: VectorState,
        *,
        expected_definition_version: int,
    ) -> Tag:
        """按定义版本条件更新标签向量状态，防止旧事件覆盖新版本。"""
        ...

    async def list_tags_by_vector_state(
        self,
        vector_state: VectorState,
        *,
        limit: int,
    ) -> list[Tag]:
        """分页读取指定向量状态的标签，供一致性对账。"""
        ...


def tag_service_from_settings(settings: Settings) -> TagServiceClient:
    """按部署配置创建具体 Tag Service 客户端，避免把工厂方法混入协议。"""
    from label_agent.infrastructure.tag_service.http_client import TagServiceHttpClient

    return TagServiceHttpClient(
        base_url=settings.tag_service_base_url,
        timeout_ms=settings.tag_service_timeout_ms,
        auth_token=settings.tag_service_auth_token,
    )
