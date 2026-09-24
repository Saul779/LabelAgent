"""JobContext：贯穿单个 Job 全部 phase 的“工作记忆”。

不是长期会话记忆——Agent 是场景路由的固定管线，不是开放式多轮对话；
JobContext 只在一次 Job 的生命周期内存在，用于在 LOAD -> ... -> PUBLISH
各阶段之间传递中间产物（感知结果、候选、提议、证据、降级标记等），
每个阶段只读取/追加自己需要的字段，不做隐式共享状态突变。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class JobContext:
    """单次 Job 生命周期内的工作记忆：在各 phase 间传递感知结果、候选、提议、证据与降级标记。"""

    job_id: str
    task_id: str
    scene: str
    biz_id: str
    payload: dict[str, Any]

    data_version: int | None = None
    version_protected: bool = True
    trace_id: str | None = None

    # 各 phase 产出，按需填充；类型引用见 domain.models
    content_bundle: Any | None = None
    category_candidates: list[Any] = field(default_factory=list)
    candidates: list[Any] = field(default_factory=list)
    semantic_proposal: Any | None = None
    resolved_entities: list[Any] = field(default_factory=list)
    evidence_bundle: Any | None = None
    degraded_modalities: list[str] = field(default_factory=list)

    policy_version: str | None = None
    prompt_version: str | None = None
    model_run_id: str | None = None

    def note_degraded(self, modality: str) -> None:
        """记录某模态已降级，供结果出参与审计使用；重复标记会被忽略。"""
        if modality not in self.degraded_modalities:
            self.degraded_modalities.append(modality)
