"""S1/S2 证书识别的证据与匹配中间模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class CertificateEvidence(BaseModel):
    """从证书材料中提取的一条职业或技能证据。"""

    id: str
    title: str
    description: str


class EnterpriseEvidence(BaseModel):
    """S1 提取的企业名称及其关联证据。"""

    name: str
    evidence_ids: list[str] = Field(default_factory=list)


class GeneratedEvidenceBatch(BaseModel):
    """一次生成调用得到的证据和企业集合。"""

    evidence: list[CertificateEvidence] = Field(default_factory=list)
    enterprises: list[EnterpriseEvidence] = Field(default_factory=list)

    @field_validator("evidence")
    @classmethod
    def _validate_evidence_limit(
        cls, evidence: list[CertificateEvidence]
    ) -> list[CertificateEvidence]:
        if len(evidence) > 5:
            raise ValueError("evidence 长度必须为 0~5")
        return evidence

    @field_validator("enterprises")
    @classmethod
    def _validate_enterprise_limit(
        cls, enterprises: list[EnterpriseEvidence]
    ) -> list[EnterpriseEvidence]:
        if len(enterprises) > 10:
            raise ValueError("enterprises 长度必须为 0~10")
        return enterprises


class MatchedEvidence(BaseModel):
    """单条证据经 Top-5 强制选择后的合法命中结果。"""

    entity_id: str
    canonical_id: str
    display_name: str
    evidence_id: str
    confidence: float = Field(ge=0.0, le=1.0)


class EvidenceConfidence(BaseModel):
    """合并后保留的单条证据置信度。"""

    id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)


class ConsolidatedMatch(BaseModel):
    """按 canonical_id 合并后的职业或技能结果。"""

    entity_id: str
    canonical_id: str
    display_name: str
    evidences: list[EvidenceConfidence] = Field(default_factory=list)


class EvidenceMatchDecision(BaseModel):
    """单条证据的业务匹配结论；拒绝/歧义不会进入 canonical_id 合并。"""

    evidence_id: str = Field(min_length=1)
    match_status: Literal["matched", "ambiguous", "no_match"]
    entity_id: str | None = None
    canonical_id: str | None = None
    display_name: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""

    @model_validator(mode="after")
    def _validate_selected_entity(self) -> EvidenceMatchDecision:
        selected = (self.entity_id, self.canonical_id, self.display_name)
        if self.match_status == "matched" and any(value is None for value in selected):
            raise ValueError("matched 状态必须包含完整命中实体")
        if self.match_status != "matched" and any(value is not None for value in selected):
            raise ValueError("非 matched 状态不得携带命中实体")
        return self


class EvidenceMatchingResult(BaseModel):
    """证据匹配阶段的完整中间结果。"""

    matched: list[ConsolidatedMatch] = Field(default_factory=list)
    decisions: list[EvidenceMatchDecision] = Field(default_factory=list)
    unmatched_evidence: list[CertificateEvidence] = Field(default_factory=list)
    dictionary_snapshot_version: str = ""
    audit: int = Field(default=0, ge=0, le=1)
