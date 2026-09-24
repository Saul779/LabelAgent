"""SemanticProposal：LLM 语义提议（§1.3）。

设计原则：模型只输出语义候选，不直接产生标签 ID、不执行写操作、
不决定最终阈值——ID 归一化、去重、写入均由 resolution/ 完成。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from label_agent.domain.models.candidate import NewTagRequest


class ProposedCategory(BaseModel):
    """语义提议中的类目建议项。"""

    category_id: str  # 必须引用 CandidateRetriever 提供的候选 ID
    model_score: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[dict] = Field(default_factory=list)


class ProposedTag(BaseModel):
    """语义提议中的标签建议项。"""

    tag_id: str | None = None  # 引用候选 ID；为空表示 new_tag_requested
    new_tag_request: NewTagRequest | None = None
    model_score: float = Field(ge=0.0, le=1.0)
    evidence_refs: list[dict] = Field(default_factory=list)


class SemanticProposal(BaseModel):
    """LLM 语义提议整体结构（类目+标签+元数据）。"""

    model_run_id: str
    prompt_version: str
    primary_category: ProposedCategory | None = None
    secondary_category: ProposedCategory | None = None
    tags: list[ProposedTag] = Field(default_factory=list)
    raw_model_output_ref: str | None = None  # 指向原始输出存储位置，不在契约内内联大文本
