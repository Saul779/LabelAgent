"""候选召回结果（§5.1.3）。

候选携带 tag_id/canonical_tag_id/dictionary_snapshot_version；
模型只能引用候选 ID，不得自行生成 ID。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class TagCandidate(BaseModel):
    """召回得到的标签候选。"""

    tag_id: str
    canonical_tag_id: str
    display_name: str
    canonical_display_name: str | None = None
    name_type: str  # standard | alias
    domain: str
    dictionary_snapshot_version: str
    match_source: str  # exact | alias | bm25 | vector
    match_score: float
    vector_state: str = "READY"  # PENDING | READY | FAILED
    metadata: dict[str, Any] = Field(default_factory=dict)


class CategoryCandidate(BaseModel):
    """召回得到的类目候选。"""

    category_id: str
    name: str
    domain: str
    dictionary_snapshot_version: str
    level: int = 1
    parent_category_id: str | None = None


class NewTagRequest(BaseModel):
    """召回失败或候选为空时提出的建标请求，需经 §6.2 安全门禁后才可创建。"""

    proposed_name: str
    domain: str
    reason: str
