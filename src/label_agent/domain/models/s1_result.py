"""S1 职业识别精简输出契约。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class RecognitionEvidence(BaseModel):
    """对外返回的原始职业证据。"""

    evidence_id: str = Field(min_length=1)
    title: str
    description: str


class OccupationEvidenceMatch(BaseModel):
    """标准职业与单条证据之间的匹配关系。"""

    evidence_id: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class OccupationMatch(BaseModel):
    """按职业词典 canonical_id 合并后的职业命中。"""

    occupation_id: str = Field(min_length=1)
    occupation_name: str = Field(min_length=1)
    evidences: list[OccupationEvidenceMatch] = Field(min_length=1)

    @field_validator("evidences")
    @classmethod
    def _validate_evidences(
        cls, evidences: list[OccupationEvidenceMatch]
    ) -> list[OccupationEvidenceMatch]:
        evidence_ids = [item.evidence_id for item in evidences]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("同一 occupation 的 evidences.evidence_id 必须唯一")
        return evidences


class UnmatchedOccupation(BaseModel):
    """S1 未匹配的职业证据结论。"""

    evidence_id: str = Field(min_length=1)
    match_status: Literal["no_match"] = "no_match"
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class CareerRecognitionResult(BaseModel):
    """S1 最终结果；只暴露业务方需要的四个字段。"""

    occupations: list[OccupationMatch] = Field(default_factory=list)
    unmatched: list[UnmatchedOccupation] = Field(default_factory=list)
    evidence: list[RecognitionEvidence] = Field(default_factory=list)
    enterprises: list[str] = Field(default_factory=list)
    audit: int = Field(default=0, ge=0, le=1)

    @field_validator("occupations")
    @classmethod
    def _validate_occupations(cls, occupations: list[OccupationMatch]) -> list[OccupationMatch]:
        if len(occupations) > 5:
            raise ValueError("occupations 长度必须为 0~5")
        occupation_ids = [item.occupation_id for item in occupations]
        if len(occupation_ids) != len(set(occupation_ids)):
            raise ValueError("occupations 必须按 canonical_id 去重")
        return occupations

    @field_validator("evidence")
    @classmethod
    def _validate_evidence(cls, evidence: list[RecognitionEvidence]) -> list[RecognitionEvidence]:
        if len(evidence) > 5:
            raise ValueError("evidence 长度必须为 0~5")
        return evidence

    @field_validator("enterprises")
    @classmethod
    def _validate_enterprises(cls, enterprises: list[str]) -> list[str]:
        if len(enterprises) > 10:
            raise ValueError("enterprises 长度必须为 0~10")
        if any(not name.strip() for name in enterprises):
            raise ValueError("enterprises 不允许空名称")
        normalized_names = [name.strip().casefold() for name in enterprises]
        if len(normalized_names) != len(set(normalized_names)):
            raise ValueError("enterprises 必须按名称去重")
        return enterprises

    def to_receipt_payload(self) -> dict:
        """转换为可直接放入回执 payload 的字典形式。"""
        return self.model_dump()
