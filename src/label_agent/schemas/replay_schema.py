"""DLQ 重放相关 DTO。"""

from __future__ import annotations

from pydantic import BaseModel


class ReplayRequest(BaseModel):
    """Job 重放请求体。"""

    job_id: str
    operator: str


class ReplayResponse(BaseModel):
    """Job 重放响应体。"""

    job_id: str
    replay_generation: str
