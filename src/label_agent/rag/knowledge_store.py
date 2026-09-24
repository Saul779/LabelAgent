"""知识库向量存储适配：默认复用 Milvus 代理，独立 collection，不与 tag/user 向量混存。"""

from __future__ import annotations

from label_agent.infrastructure.milvus_proxy.client import MilvusProxyClient
from label_agent.rag.base import KnowledgeChunk


class VectorKnowledgeStore:
    """基于向量的知识存储与检索实现。"""

    def __init__(self, milvus_proxy: MilvusProxyClient, collection: str) -> None:
        """注入向量库与嵌入依赖。"""
        self._milvus_proxy = milvus_proxy
        self._collection = collection

    async def search(self, query_embedding: list[float], top_k: int) -> list[KnowledgeChunk]:
        raise NotImplementedError

    async def upsert(self, chunks: list[KnowledgeChunk], embeddings: list[list[float]]) -> None:
        raise NotImplementedError
