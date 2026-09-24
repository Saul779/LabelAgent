"""RAG 扩展点：面向 Prompt 增强的知识检索，与 retrieval/（标签/分类域结构化召回）职责分离。

当前 S3/T1 固定管线不依赖本模块（`rag.enabled=false`）；预留给未来场景
（如 S1/S2 证书类目知识库、规则文档辅助判定）按需接入，接入方式只需实现
`KnowledgeRetriever` 并注册，不改动 inference/scenarios 主流程代码。
"""
