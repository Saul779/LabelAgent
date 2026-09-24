"""分类查询 Tool：只读，分类库任何路径都不得提供创建接口（§1 设计原则 7）。"""

from __future__ import annotations

from label_agent.retrieval.candidate_retriever import CandidateRetriever


class CategoryLookupTool:
    """查询类目的工具。"""

    name = "category_lookup"
    description = "按 domain 查询一级/二级分类字典，只读"
    parameters_schema = {
        "type": "object",
        "properties": {"domain": {"type": "string"}},
        "required": ["domain"],
    }

    def __init__(self, candidate_retriever: CandidateRetriever) -> None:
        """注入类目查询依赖。"""
        self._candidate_retriever = candidate_retriever

    async def invoke(self, domain: str) -> list[dict]:
        raise NotImplementedError
