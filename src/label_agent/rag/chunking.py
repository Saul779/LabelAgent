"""知识文档切片：供未来知识库构建流程使用。"""

from __future__ import annotations


def chunk_text(text: str, max_chars: int = 500, overlap: int = 50) -> list[str]:
    """将长文本切分为知识块。"""
    if max_chars <= overlap:
        raise ValueError("max_chars 必须大于 overlap")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        chunks.append(text[start:end])
        start = end - overlap
    return chunks
