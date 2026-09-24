"""编排层：Orchestrator、ProcessTask 与对外用例（use_cases）。

本层只做流程编排与依赖装配，不实现具体业务规则——规则位于
domain/scenarios/validation 等模块，便于替换而不改动编排代码。
"""
