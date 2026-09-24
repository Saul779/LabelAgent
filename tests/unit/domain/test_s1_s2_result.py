"""S1/S2 schema 2.0 输出契约校验。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from label_agent.domain.models.s1_result import CareerRecognitionResult
from label_agent.domain.models.s2_result import CertificateRecognitionResult


def _meta() -> dict[str, str]:
    return {
        "biz_id": "cert-1",
        "model_run_id": "run-1",
        "prompt_version": "v2",
        "policy_version": "certificate-match-v2",
        "dictionary_snapshot_version": "dict-v2",
    }


def test_s1_result_uses_compact_business_payload() -> None:
    result = CareerRecognitionResult(
        occupations=[
            {
                "occupation_id": "career-001",
                "occupation_name": "Python工程师",
                "evidences": [
                    {"evidence_id": "E001", "confidence": 0.91, "reason": "精确匹配"},
                    {"evidence_id": "E002", "confidence": 0.66, "reason": "语义匹配"},
                ],
            }
        ],
        evidence=[{"evidence_id": "E001", "title": "Python工程师", "description": "原文"}],
        enterprises=["示例公司"],
        audit=1,
    )
    payload = result.to_receipt_payload()
    assert payload == {
        "occupations": [
            {
                "occupation_id": "career-001",
                "occupation_name": "Python工程师",
                "evidences": [
                    {"evidence_id": "E001", "confidence": 0.91, "reason": "精确匹配"},
                    {"evidence_id": "E002", "confidence": 0.66, "reason": "语义匹配"},
                ],
            }
        ],
        "unmatched": [],
        "evidence": [{"evidence_id": "E001", "title": "Python工程师", "description": "原文"}],
        "enterprises": ["示例公司"],
        "audit": 1,
    }


def test_s1_result_rejects_duplicate_canonical_ids() -> None:
    with pytest.raises(ValidationError):
        CareerRecognitionResult(
            occupations=[
                {
                    "occupation_id": "career-001",
                    "occupation_name": "Python工程师",
                    "evidences": [{"evidence_id": "E001", "confidence": 0.9}],
                },
                {
                    "occupation_id": "career-001",
                    "occupation_name": "Python工程师",
                    "evidences": [{"evidence_id": "E002", "confidence": 0.8}],
                },
            ],
        )


def test_s1_result_rejects_duplicate_evidence_ids_in_occupation() -> None:
    with pytest.raises(ValidationError):
        CareerRecognitionResult(
            occupations=[
                {
                    "occupation_id": "career-001",
                    "occupation_name": "Python工程师",
                    "evidences": [
                        {"evidence_id": "E001", "confidence": 0.9},
                        {"evidence_id": "E001", "confidence": 0.8},
                    ],
                }
            ],
        )


def test_s1_result_rejects_more_than_ten_enterprises() -> None:
    with pytest.raises(ValidationError):
        CareerRecognitionResult(
            enterprises=[f"企业{i}" for i in range(11)],
        )


def test_s2_result_uses_certificate_ids_and_public_audit() -> None:
    result = CertificateRecognitionResult(
        **_meta(),
        certificates=[
            {
                "certificate_id": "certificate-001",
                "certificate_name": "PMP项目管理专业人士认证",
                "evidences": [{"evidence_id": "E001", "confidence": 0.96}],
            }
        ],
        evidence=[],
        audit=0,
    )
    assert result.certificates[0].certificate_id == "certificate-001"
    assert result.to_receipt_payload()["schema_version"] == "4.0"


def test_s2_result_rejects_duplicate_certificate_ids() -> None:
    with pytest.raises(ValidationError):
        CertificateRecognitionResult(
            **_meta(),
            certificates=[
                {
                    "certificate_id": "certificate-001",
                    "certificate_name": "PMP项目管理专业人士认证",
                    "evidences": [{"evidence_id": "E001", "confidence": 0.96}],
                },
                {
                    "certificate_id": "certificate-001",
                    "certificate_name": "PMP项目管理专业人士认证",
                    "evidences": [{"evidence_id": "E002", "confidence": 0.92}],
                },
            ],
        )
