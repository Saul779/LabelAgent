"""EvidenceRef 可回查校验的应用层封装（复用 domain.evidence.evidence_validator 的纯逻辑）。"""

from __future__ import annotations

from typing import Any

from pydantic import TypeAdapter, ValidationError

from label_agent.core.context import JobContext
from label_agent.core.exceptions import EvidenceValidationError
from label_agent.domain.evidence.evidence_validator import validate_evidence_ref
from label_agent.domain.models.evidence import EvidenceRef

_EVIDENCE_REF_ADAPTER: TypeAdapter[EvidenceRef] = TypeAdapter(EvidenceRef)


def validate_all(ctx: JobContext, refs: list[EvidenceRef | dict[str, Any]]) -> None:
    """批量校验证据引用列表。"""
    if ctx.content_bundle is None:
        raise EvidenceValidationError("缺少 ContentBundle，无法回查证据引用")
    try:
        parsed_refs = [_EVIDENCE_REF_ADAPTER.validate_python(ref) for ref in refs]
    except ValidationError as exc:
        raise EvidenceValidationError(f"证据引用结构不合法: {exc}") from exc
    for parsed_ref in parsed_refs:
        if not validate_evidence_ref(parsed_ref, ctx.content_bundle):
            raise EvidenceValidationError(f"证据引用校验失败: {parsed_ref}")
