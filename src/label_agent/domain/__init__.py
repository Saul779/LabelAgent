"""领域层：核心数据契约（domain/models）与策略接口（domain/policies）。

约束（实现文档 §2.2）：本包不依赖任何具体 SDK/第三方 IO 客户端，
只允许依赖 pydantic/标准库，以保证可在任意基础设施实现下复用与单测。
"""
