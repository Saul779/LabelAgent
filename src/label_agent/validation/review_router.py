"""ReviewRouter 应用层封装：加载配置化触发规则并构造 domain.policies.ReviewRouter 实例（D010）。"""

from __future__ import annotations

from label_agent.domain.policies.review_router import ReviewRouter, ReviewTrigger
from label_agent.infrastructure.config_center.client import ConfigCenterClient


def build_review_router(
    config_center: ConfigCenterClient,
    triggers: list[ReviewTrigger],
) -> ReviewRouter:
    """根据配置构建领域 ReviewRouter 实例。"""
    router_version = config_center.get_str("policy.review_router.version")
    return ReviewRouter(router_version=router_version, triggers=triggers)
