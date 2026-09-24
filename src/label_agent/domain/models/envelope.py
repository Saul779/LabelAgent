"""MQ 投递信封（§3.1）。

v1 为协议基线，必须始终兼容；v2 扩展字段在 payload 内以“内部约定”形式携带，
评审通过前不得视为协议正式字段。命名约束：`payload_type`（协议层类型）与
T1 的业务 `biz_task_type` 是不同层级字段，禁止复用同一变量名。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TaskEnvelopeV1(BaseModel):
    """协议基线（已确认，当前必须兼容）。"""

    task_id: str
    task_type: str
    payload_type: str
    payload: dict[str, Any]
    priority: int = Field(ge=1, le=3)
    timestamp: int
    callback_topic: str


class EnvelopeV2Extension(BaseModel):
    """v2 扩展字段（暂定，A026），从 payload 内以 `payload.get(...)` 安全读取。

    任一字段缺失都必须走降级默认值，不得阻断处理：
    - event_id 缺失 -> 用 task_id 兜底，并记录 degraded_idempotency=true；
    - biz_id/data_version 缺失 -> 无法做版本保护，记录 version_protected=false。
    """

    event_id: str | None = None
    biz_id: str | None = None
    data_version: int | None = None
    scene: str | None = None
    resource_uris: list[str] = Field(default_factory=list)
    payload_hash: str | None = None
    trace_id: str | None = None
    biz_task_type: str | None = None


class ParsedEnvelope(BaseModel):
    """`EnvelopeParser` 的统一输出，供 Job 执行层使用，屏蔽 v1/v2 差异。"""

    v1: TaskEnvelopeV1
    v2: EnvelopeV2Extension
    degraded_idempotency: bool = False
    version_protected: bool = True

    @property
    def effective_event_id(self) -> str:
        """有效事件 ID：优先 v2.event_id，否则回退 v1.task_id，供幂等与追踪使用。"""
        return self.v2.event_id or self.v1.task_id
