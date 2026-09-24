"""EvidenceRef 可回查校验（§3.4、§7.1）：越界/内容不一致必须被拒绝。"""

from __future__ import annotations

import pytest

from label_agent.core.context import JobContext
from label_agent.core.exceptions import EvidenceValidationError
from label_agent.domain.evidence.evidence_validator import validate_evidence_ref
from label_agent.domain.models.evidence import TextEvidenceRef
from label_agent.validation.evidence_ref_validator import validate_all


def test_valid_text_evidence_ref(sample_content_bundle) -> None:
    text = sample_content_bundle.normalized_text
    ref = TextEvidenceRef(
        asset_id="a1", char_start=0, char_end=len(text), quote=text, content_hash="sha256:x"
    )
    assert validate_evidence_ref(ref, sample_content_bundle) is True


def test_out_of_range_evidence_ref_is_rejected(sample_content_bundle) -> None:
    ref = TextEvidenceRef(
        asset_id="a1", char_start=0, char_end=9999, quote="不存在", content_hash="sha256:x"
    )
    assert validate_evidence_ref(ref, sample_content_bundle) is False


def test_mismatched_quote_is_rejected(sample_content_bundle) -> None:
    ref = TextEvidenceRef(
        asset_id="a1", char_start=0, char_end=5, quote="完全不匹配的引用", content_hash="sha256:x"
    )
    assert validate_evidence_ref(ref, sample_content_bundle) is False


def test_validate_all_parses_model_output_dict(sample_content_bundle) -> None:
    """验证应用层校验器可直接处理模型输出的字典结构。"""
    text = sample_content_bundle.normalized_text
    ctx = JobContext("job-1", "task-1", "S3", "biz-1", {})
    ctx.content_bundle = sample_content_bundle

    validate_all(
        ctx,
        [
            {
                "type": "text",
                "asset_id": "a1",
                "char_start": 0,
                "char_end": len(text),
                "quote": text,
                "content_hash": "sha256:x",
            }
        ],
    )


def test_validate_all_rejects_invalid_dict(sample_content_bundle) -> None:
    """验证缺少必填字段的模型证据引用会在写入前被拒绝。"""
    ctx = JobContext("job-1", "task-1", "S3", "biz-1", {})
    ctx.content_bundle = sample_content_bundle

    with pytest.raises(EvidenceValidationError, match="证据引用结构不合法"):
        validate_all(ctx, [{"type": "text", "asset_id": "a1"}])
