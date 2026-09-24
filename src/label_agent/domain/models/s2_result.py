"""S2 技能证书识别输出契约（schema 4.0）。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RecognitionEvidence(BaseModel):
    """对外返回的原始证书证据。"""

    evidence_id: str = Field(min_length=1)
    title: str
    description: str


class CertificateEvidenceMatch(BaseModel):
    """标准证书与单条证据之间的匹配关系。"""

    evidence_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class CertificateMatch(BaseModel):
    """按证书词典 canonical_id 合并后的标准证书命中。"""

    certificate_id: str = Field(min_length=1)
    certificate_name: str = Field(min_length=1)
    evidences: list[CertificateEvidenceMatch] = Field(min_length=1)

    @field_validator("evidences")
    @classmethod
    def _validate_evidences(
        cls, evidences: list[CertificateEvidenceMatch]
    ) -> list[CertificateEvidenceMatch]:
        evidence_ids = [item.evidence_id for item in evidences]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("同一 certificate 的 evidences.evidence_id 必须唯一")
        return evidences


class UnmatchedCertificate(BaseModel):
    """S2 未明确匹配的证书证据结论。"""

    evidence_id: str = Field(min_length=1)
    match_status: Literal["ambiguous", "no_match"]
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class CertificateRecognitionResult(BaseModel):
    """S2 最终结果；识别并匹配标准技能证书，不输出通用技能标签。"""

    schema_version: str = "4.0"
    biz_id: str
    model_run_id: str
    prompt_version: str
    policy_version: str
    dictionary_snapshot_version: str
    certificates: list[CertificateMatch] = Field(default_factory=list)
    unmatched: list[UnmatchedCertificate] = Field(default_factory=list)
    evidence: list[RecognitionEvidence] = Field(default_factory=list)
    audit: int = Field(default=0, ge=0, le=1)
    degraded_modalities: list[str] = Field(default_factory=list)
    perception_versions: dict[str, str] = Field(default_factory=dict)

    @field_validator("certificates")
    @classmethod
    def _validate_certificates(cls, certificates: list[CertificateMatch]) -> list[CertificateMatch]:
        if len(certificates) > 5:
            raise ValueError("certificates 长度必须为 0~5")
        certificate_ids = [item.certificate_id for item in certificates]
        if len(certificate_ids) != len(set(certificate_ids)):
            raise ValueError("certificates 必须按 canonical_id 去重")
        return certificates

    @field_validator("evidence")
    @classmethod
    def _validate_evidence(cls, evidence: list[RecognitionEvidence]) -> list[RecognitionEvidence]:
        if len(evidence) > 5:
            raise ValueError("evidence 长度必须为 0~5")
        return evidence

    def to_receipt_payload(self) -> dict:
        """转换为可直接放入回执 payload 的字典形式。"""
        return self.model_dump()
