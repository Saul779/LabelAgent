"""S1/S2 生成式候选（§5.3）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class GeneratedCandidate(BaseModel):
    """LLM 自由生成的候选，不产生最终 ID、不执行写操作。"""

    display_name: str
    model_score: float = Field(ge=0.0, le=1.0)
    structured_fields: dict = Field(default_factory=dict)
    evidence_refs: list[dict] = Field(default_factory=list)
