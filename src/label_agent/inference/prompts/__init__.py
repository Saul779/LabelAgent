"""Prompt 版本管理：模板文件（templates/）+ PromptManager 按版本号加载。

命名约定：`<scene>-v<N>.yaml`，与 domain 结果契约中的 `prompt_version` 字段对应，
每次结果都需记录所用版本号以便回溯（§0 实现约束第 3 条）。
"""
