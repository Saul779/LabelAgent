"""MQ 端口抽象：业务与 Worker 只依赖本模块，便于 mock ↔ 真实 MQ 切换。"""

from __future__ import annotations

from typing import Protocol

from label_agent.domain.models.receipt import Receipt


class MqPublisher(Protocol):
    """出站发布端口：将回执投递到 callback_topic。"""

    async def publish(self, callback_topic: str, receipt: Receipt) -> None:
        """发布回执；实现方须先校验 callback_topic 白名单。"""
        ...


class MqIngressConsumer(Protocol):
    """入站消费端口：拉取任务信封并交给 ProcessTask 执行。"""

    async def run_forever(self) -> None:
        """持续拉取并处理任务，直到进程收到停止信号。"""
        ...

    async def poll_once(self) -> bool | None:
        """拉取并处理至多一条消息；有消费返回 True，队列空返回 False。"""
        ...
