"""运维任务相关 DTO。"""

from __future__ import annotations

from pydantic import BaseModel


class ProfileTriggerRequest(BaseModel):
    """触发画像 Job 的请求体。"""

    user_id: str
    operator: str


class ProfileTriggerResponse(BaseModel):
    """触发画像 Job 的响应体。"""

    job_id: str
