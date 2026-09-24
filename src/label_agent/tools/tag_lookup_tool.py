"""标签查询 Tool：只读包装 retrieval.CandidateRetriever。"""

from __future__ import annotations

from label_agent.retrieval.candidate_retriever import CandidateRetriever


class TagLookupTool:
    """按关键词/ID 查询标签的工具。"""

    name = "tag_lookup"
    description = "按关键词与 domain 查询已存在的标准标签/别名，只读，不创建标签"
    parameters_schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "domain": {"type": "string"},
        },
        "required": ["query", "domain"],
    }

    def __init__(self, candidate_retriever: CandidateRetriever) -> None:
        """注入 Tag Service 客户端。"""
        self._candidate_retriever = candidate_retriever

    async def invoke(self, query: str, domain: str) -> list[dict]:
        raise NotImplementedError
