"""S2 回执必须使用去冗余后的标准技能证书 schema 4.0 契约。"""

from __future__ import annotations

from label_agent.domain.models.s2_result import CertificateRecognitionResult


def test_s2_receipt_uses_certificate_ids_without_legacy_skills() -> None:
    result = CertificateRecognitionResult(
        biz_id="certificate-001",
        model_run_id="run-001",
        prompt_version="s2-v3",
        policy_version="certificate-match-v2",
        dictionary_snapshot_version="dict-certificate-2026-08-18",
        certificates=[
            {
                "certificate_id": "certificate-001",
                "certificate_name": "PMP项目管理专业人士认证",
                "evidences": [
                    {"evidence_id": "E001", "confidence": 0.96, "reason": "名称及机构一致"}
                ],
            }
        ],
        evidence=[],
        audit=0,
    )

    payload = result.to_receipt_payload()

    assert payload["schema_version"] == "4.0"
    assert payload["certificates"] == [
        {
            "certificate_id": "certificate-001",
            "certificate_name": "PMP项目管理专业人士认证",
            "evidences": [{"evidence_id": "E001", "confidence": 0.96, "reason": "名称及机构一致"}],
        }
    ]
    assert "skills" not in payload
    assert payload["unmatched"] == []
    assert "match_results" not in payload
