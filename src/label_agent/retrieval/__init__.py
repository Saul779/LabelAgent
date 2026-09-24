"""候选召回与融合（§5.1.3）：面向标签/分类域的结构化检索，
区别于 rag/（面向 Prompt 增强的知识检索）。

多路并行召回（归一化精确匹配/别名匹配/n-gram-BM25/向量近义检索），
按 domain（D009）、scene、status、category 过滤，RRF 融合。
"""
