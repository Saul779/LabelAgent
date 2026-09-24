"""rule-mvp-1 策略：复用 domain.confidence.default_policy 的默认公式，系数从配置中心加载。"""

from __future__ import annotations

from label_agent.domain.confidence.default_policy import ProvisionalRuleMvp1
from label_agent.infrastructure.config_center.client import ConfigCenterClient


def build_rule_mvp_1(config_center: ConfigCenterClient) -> ProvisionalRuleMvp1:
    """构建 provisional-rule-mvp-1 规则包。"""
    coefficients = config_center.get_json("policy.confidence.rule_mvp_1.coefficients")
    return ProvisionalRuleMvp1(
        evidence_factor=coefficients["evidence_factor"],
        consistency_factor=coefficients["consistency_factor"],
        stability_factor=coefficients["stability_factor"],
    )
