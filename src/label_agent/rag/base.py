"""KnowledgeRetriever 协议：RAG 扩展的统一接口。"""

from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel


class KnowledgeChunk(BaseModel):
    """知识库切分后的文本块。"""

    chunk_id: str
    source: str
    text: str
    score: float


class KnowledgeRetriever(Protocol):
    """知识检索抽象接口。"""

    knowledge_base_id: str

    async def retrieve(self, query: str, top_k: int = 5) -> list[KnowledgeChunk]: ...
