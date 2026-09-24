"""S2 技能证书识别管线（schema 4.0）。"""

from __future__ import annotations

import logging
import uuid

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NeedReviewError, SafetyGateRejectedError
from label_agent.domain.models.certificate_evidence import CertificateEvidence
from label_agent.domain.models.s2_result import (
    CertificateEvidenceMatch,
    CertificateMatch,
    CertificateRecognitionResult,
    RecognitionEvidence,
    UnmatchedCertificate,
)
from label_agent.inference.generative_proposer import GenerativeProposer
from label_agent.perception.certificate_content_loader import CertificateContentLoader
from label_agent.resolution.evidence_candidate_matcher import EvidenceCandidateMatcher
from label_agent.validation.safety.injection_detector import InjectionDetector
from label_agent.validation.safety.pii_detector import PiiDetector

logger = logging.getLogger(__name__)


class S2Pipeline:
    """感知 → 技能证书证据提取 → 逐证据 Top-5 五选一 → 合并 → 输出。"""

    def __init__(
        self,
        content_loader: CertificateContentLoader,
        generative_proposer: GenerativeProposer,
        matcher: EvidenceCandidateMatcher,
        pii_detector: PiiDetector,
        injection_detector: InjectionDetector,
        *,
        prompt_version: str = "s2-v3",
        policy_version: str = "certificate-match-v2",
        dictionary_snapshot_version: str = "",
    ) -> None:
        self._content_loader = content_loader
        self._proposer = generative_proposer
        self._matcher = matcher
        self._pii = pii_detector
        self._injection = injection_detector
        self._prompt_version = prompt_version
        self._policy_version = policy_version
        self._dictionary_snapshot_version = dictionary_snapshot_version

    async def run(self, ctx: JobContext) -> CertificateRecognitionResult:
        ctx.content_bundle = await self._content_loader.build(ctx)
        ctx.prompt_version = self._prompt_version
        ctx.policy_version = self._policy_version
        ctx.model_run_id = ctx.model_run_id or f"run-{uuid.uuid4().hex[:12]}"

        try:
            generated = await self._proposer.propose_evidence(
                ctx,
                domain="certificate",
                prompt_version=self._prompt_version,
                scene="s2",
                evidence_key="certificate_evidence",
            )
        except NeedReviewError as exc:
            logger.warning("S2 技能证据解析失败，返回空结果: %s", exc)
            return self._result(ctx, certificates=[], evidence=[], audit=0)

        safe_evidence = self._filter_unsafe(generated.evidence)
        matching = await self._matcher.match(safe_evidence, scene="s2")
        decisions = {item.evidence_id: item for item in matching.decisions}
        return self._result(
            ctx,
            certificates=[
                CertificateMatch(
                    certificate_id=item.canonical_id,
                    certificate_name=item.display_name,
                    evidences=[
                        CertificateEvidenceMatch(
                            evidence_id=ref.id,
                            confidence=ref.confidence,
                            reason=decisions[ref.id].reason,
                        )
                        for ref in item.evidences
                    ],
                )
                for item in matching.matched
            ],
            unmatched=[
                UnmatchedCertificate(
                    evidence_id=item.evidence_id,
                    match_status=item.match_status,
                    confidence=item.confidence,
                    reason=item.reason,
                )
                for item in matching.decisions
                if item.match_status in {"ambiguous", "no_match"}
            ],
            evidence=[
                RecognitionEvidence(
                    evidence_id=item.id,
                    title=item.title,
                    description=item.description,
                )
                for item in safe_evidence
            ],
            dictionary_snapshot_version=matching.dictionary_snapshot_version,
            audit=matching.audit,
        )

    def _result(
        self,
        ctx: JobContext,
        *,
        certificates: list[CertificateMatch],
        unmatched: list[UnmatchedCertificate] | None = None,
        evidence: list[RecognitionEvidence],
        audit: int,
        dictionary_snapshot_version: str = "",
    ) -> CertificateRecognitionResult:
        return CertificateRecognitionResult(
            biz_id=ctx.biz_id,
            model_run_id=ctx.model_run_id or "",
            prompt_version=self._prompt_version,
            policy_version=self._policy_version,
            dictionary_snapshot_version=(
                dictionary_snapshot_version or self._dictionary_snapshot_version
            ),
            certificates=certificates,
            unmatched=unmatched or [],
            evidence=evidence,
            audit=audit,
            degraded_modalities=list(ctx.degraded_modalities),
            perception_versions=(
                dict(ctx.content_bundle.perception_versions) if ctx.content_bundle else {}
            ),
        )

    def _filter_unsafe(self, evidence: list[CertificateEvidence]) -> list[CertificateEvidence]:
        kept: list[CertificateEvidence] = []
        for item in evidence:
            try:
                self._pii.assert_clean(item.title)
                self._injection.assert_clean(item.title)
            except SafetyGateRejectedError as exc:
                logger.info("丢弃不安全技能证据 id=%s reason=%s", item.id, exc)
                continue
            kept.append(item)
        return kept
