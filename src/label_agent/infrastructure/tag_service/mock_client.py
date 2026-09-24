"""内存 Mock 实现：用于单测/联调，实施顺序 §11 第 2 步（Tag Service Client 接口 + Mock 实现）。"""

from __future__ import annotations

from label_agent.domain.models.candidate import CategoryCandidate, TagCandidate
from label_agent.domain.models.tag import LifecycleStatus, Tag, VectorState


class MockTagServiceClient:
    """TagServiceClient 的内存 Mock 实现：用于单测/本地联调，不依赖真实 Tag Service。"""

    def __init__(self) -> None:
        """用内存数据模拟 Tag Service，供本地/测试。"""
        self._tags: dict[str, Tag] = {}

    async def search_tags(self, query: str, domain: str) -> list[TagCandidate]:
        """始终返回空列表，模拟词表中无匹配标签的场景。"""
        return []

    async def search_categories(self, domain: str) -> list[CategoryCandidate]:
        """始终返回空列表，模拟分类字典为空的场景。"""
        return []

    async def create_tag(self, proposed_name: str, domain: str, idempotency_key: str) -> Tag:
        """按幂等键生成确定性 tag_id 并创建标签，写入内存字典模拟落库。"""
        tag_id = f"tag-{idempotency_key}"
        existing = self._tags.get(tag_id)
        if existing is not None:
            return existing
        tag = Tag(
            tag_id=tag_id,
            canonical_tag_id=tag_id,
            display_name=proposed_name,
            name_type="standard",
            domain=domain,
            lifecycle_status=LifecycleStatus.ACTIVE,
            vector_state=VectorState.PENDING,
            tag_definition_version=1,
            embedding_space_id="default",
        )
        self._tags[tag.tag_id] = tag
        return tag

    async def get_tag(self, tag_id: str) -> Tag | None:
        """按 ID 查询模拟标签。"""
        return self._tags.get(tag_id)

    async def update_vector_state(
        self,
        tag_id: str,
        vector_state: VectorState,
        *,
        expected_definition_version: int,
    ) -> Tag:
        """模拟带版本保护的向量状态回写。"""
        tag = self._tags[tag_id]
        if tag.tag_definition_version != expected_definition_version:
            raise ValueError("标签定义版本不匹配")
        updated = tag.model_copy(update={"vector_state": vector_state})
        self._tags[tag_id] = updated
        return updated

    async def list_tags_by_vector_state(
        self,
        vector_state: VectorState,
        *,
        limit: int,
    ) -> list[Tag]:
        """返回指定向量状态的模拟标签。"""
        return [tag for tag in self._tags.values() if tag.vector_state == vector_state][:limit]
