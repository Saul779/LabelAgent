"""RagContextBuilder：将检索到的知识片段拼装为可注入 Prompt 的上下文块。

安全约束（§8）：拼装结果仍是“不可信数据”，只能作为 Prompt 的补充上下文，
不能改变系统 Prompt 或触发工具调用，最终仍需经 guardrails 处理。
"""

from __future__ import annotations

from label_agent.rag.base import KnowledgeChunk, KnowledgeRetriever


class RagContextBuilder:
    """把检索到的知识块拼装为可供 Prompt 使用的上下文。"""

    def __init__(self, retriever: KnowledgeRetriever) -> None:
        """注入知识检索器。"""
        self._retriever = retriever

    async def build(self, query: str, top_k: int = 5) -> str:
        """按查询检索并构建 RAG 上下文文本。"""
        chunks: list[KnowledgeChunk] = await self._retriever.retrieve(query, top_k=top_k)
        return "\n\n".join(f"[{c.source}] {c.text}" for c in chunks)
