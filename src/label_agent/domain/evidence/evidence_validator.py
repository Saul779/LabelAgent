"""EvidenceRef 可回查校验（§7.1 第 3 条）。

纯领域逻辑：给定 EvidenceRef 与其引用的 ContentBundle，校验引用未越界、
内容 Hash 一致；不做任何 IO（asset 内容已由 perception 层加载进 ContentBundle）。
"""

from __future__ import annotations

from label_agent.domain.models.content import ContentBundle
from label_agent.domain.models.evidence import EvidenceRef, TextEvidenceRef


def validate_evidence_ref(ref: EvidenceRef, content: ContentBundle) -> bool:
    """校验单条证据引用是否完整合法。"""
    if isinstance(ref, TextEvidenceRef):
        text = content.normalized_text
        if ref.char_end > len(text) or ref.char_start < 0 or ref.char_start >= ref.char_end:
            return False
        return text[ref.char_start : ref.char_end] == ref.quote
    # 其它模态的校验规则待补充（图片 bbox 越界、视频帧存在性、ASR 时间窗口等）
    return True
