"""LLM Gateway、多模型切换、Prompt 版本管理（§1.3、§8）。

安全约束：LLM Gateway 无 Tag Service / MQ / Milvus 写权限，
写操作全部在 resolution.TagCommitter 完成，回执由 ProcessTask 直接发布。
"""
