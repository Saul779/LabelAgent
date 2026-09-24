"""标签向量化事件契约。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TagCreatedEvent(BaseModel):
    """Tag Service 在标签创建事务提交后发布的事件。"""

    event_id: str
    tag_id: str
    tag_definition_version: int = Field(ge=1)
    embedding_space_id: str


class ReceivedTagCreatedEvent(BaseModel):
    """携带 MQ 确认游标的标签创建事件。"""

    event: TagCreatedEvent
    ack_token: str
