"""标签向量生成与 Milvus 代理写入（§6.3）。"""

from __future__ import annotations

from label_agent.domain.models.tag import Tag
from label_agent.inference.embeddings.base import EmbeddingProvider
from label_agent.infrastructure.milvus_proxy.client import MilvusProxyClient


class TagVectorizer:
    """标签文本向量化，供索引与相似度计算。"""

    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        milvus_proxy: MilvusProxyClient,
        *,
        collection: str = "tag_vectors",
    ) -> None:
        """注入 Embedding Provider 与 Milvus 代理。"""
        self._embedding_provider = embedding_provider
        self._milvus_proxy = milvus_proxy
        self._collection = collection

    async def vectorize_and_upsert(self, tag: Tag) -> None:
        """生成标签向量，并以定义版本和向量空间组成稳定写入 ID。"""
        vectors = await self._embedding_provider.embed([tag.display_name])
        if len(vectors) != 1 or not vectors[0]:
            raise RuntimeError(f"标签向量生成结果无效: {tag.tag_id}")
        vector_id = f"{tag.tag_id}:{tag.tag_definition_version}:{tag.embedding_space_id}"
        await self._milvus_proxy.upsert(
            self._collection,
            [vector_id],
            vectors,
            [
                {
                    "tag_id": tag.tag_id,
                    "canonical_tag_id": tag.canonical_tag_id,
                    "domain": tag.domain,
                    "tag_definition_version": tag.tag_definition_version,
                    "embedding_space_id": tag.embedding_space_id,
                }
            ],
        )
