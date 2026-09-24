"""策略版本加载与回放支持。

产品冻结规则前，使用 provisional_policy_version 标记结果，明确该结果
不代表最终验收口径；回放时通过 policy_version 重新解析历史 Job 的策略实现。
"""

from __future__ import annotations

PROVISIONAL_PREFIX = "provisional-"


def is_provisional(policy_version: str) -> bool:
    """判断策略/规则版本是否为临时（provisional）版本。"""
    return policy_version.startswith(PROVISIONAL_PREFIX)


def mark_provisional(policy_version: str) -> str:
    """将版本标记为 provisional。"""
    if is_provisional(policy_version):
        return policy_version
    return f"{PROVISIONAL_PREFIX}{policy_version}"
