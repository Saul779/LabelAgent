"""标签生命周期与向量一致性状态机（§6.3）。

lifecycle_status（词表可见性）与 vector_state（是否可参与召回）正交，
创建后立即 ACTIVE + PENDING，向量 READY 后才可安全参与 ANN 召回。
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class LifecycleStatus(str, Enum):
    """标签生命周期状态。"""

    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    MERGED = "MERGED"


class VectorState(str, Enum):
    """标签向量就绪状态（READY/PENDING 等）。"""

    PENDING = "PENDING"
    READY = "READY"
    FAILED = "FAILED"


class Tag(BaseModel):
    """标签领域实体。"""

    tag_id: str
    canonical_tag_id: str
    display_name: str
    name_type: str  # standard | alias
    domain: str
    lifecycle_status: LifecycleStatus
    vector_state: VectorState
    tag_definition_version: int
    embedding_space_id: str
