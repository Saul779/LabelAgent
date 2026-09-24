"""多 Agent 扩展点：每个场景（S3/T1/S1/S2/S4）是一个独立注册的 ScenarioHandler。

新增场景或调整某场景的必经阶段，只需注册新的 ScenarioHandler，
不改动 Consumer / JobWorker / 回执发布路径（实现文档 §2.3）。
"""
