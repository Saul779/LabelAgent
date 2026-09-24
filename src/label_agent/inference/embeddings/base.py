"""EmbeddingProvider Protocol。"""

from __future__ import annotations

from typing import Protocol


class EmbeddingProvider(Protocol):
    """向量嵌入 Provider 抽象接口。"""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """将文本批量转为向量。"""
        ...
