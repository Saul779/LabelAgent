"""用户向量生成（§5.4）：user_vectors 独立 collection，禁止与 tag_vectors 混存。"""

from __future__ import annotations

from label_agent.infrastructure.milvus_proxy.client import MilvusProxyClient


class UserVectorizer:
    """用户画像特征向量化。"""

    def __init__(self, milvus_proxy: MilvusProxyClient, collection: str = "user_vectors") -> None:
        """注入 Embedding Provider。"""
        self._milvus_proxy = milvus_proxy
        self._collection = collection

    async def vectorize_and_upsert(
        self,
        user_id: str,
        weighted_tags: list[tuple[str, float]],
    ) -> None:
        raise NotImplementedError
