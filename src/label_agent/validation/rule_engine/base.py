"""规则引擎加载器：从配置中心读取 policy.confidence.version 并解析到具体实现。"""

from __future__ import annotations

from label_agent.domain.policies.confidence_policy import ConfidencePolicy, ConfidencePolicyRegistry


class RuleEngineLoader:
    """规则引擎加载器：按版本加载校验/置信度规则。"""

    def __init__(self, registry: ConfidencePolicyRegistry) -> None:
        """初始化加载器。"""
        self._registry = registry

    def load(self, policy_version: str) -> ConfidencePolicy:
        """加载指定版本规则包。"""
        return self._registry.resolve(policy_version)
