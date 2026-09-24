"""人工审核路由接口（§7.3，D010）。

默认触发条件：无法解析/JSON 不合规、分类不在库、新标签安全门禁未通过、
证据引用校验失败、视频/图片解析部分失败且影响最终分类。
规则集独立配置，可随产品结论调整触发条件，不改动主流程代码。
"""

from __future__ import annotations

from typing import Protocol

from label_agent.core.context import JobContext


class ReviewTrigger(Protocol):
    """触发人工复核的原因/信号。"""

    reason_code: str

    def matches(self, ctx: JobContext) -> bool: ...


class ReviewRouter:
    """根据策略决定结果是否进入人工复核。"""

    router_version: str

    def __init__(self, router_version: str, triggers: list[ReviewTrigger]) -> None:
        """配置复核触发规则。"""
        self.router_version = router_version
        self._triggers = triggers

    def should_review(self, ctx: JobContext) -> str | None:
        """判断当前结果是否需要人工复核。"""
        for trigger in self._triggers:
            if trigger.matches(ctx):
                return trigger.reason_code
        return None
