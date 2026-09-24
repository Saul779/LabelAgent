"""S1/S2：逐证据 Top-5 检索、可拒绝的 LLM 匹配与 canonical_id 合并。"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from label_agent.core.exceptions import RetryableError
from label_agent.domain.models.certificate_evidence import (
    CertificateEvidence,
    ConsolidatedMatch,
    EvidenceConfidence,
    EvidenceMatchDecision,
    EvidenceMatchingResult,
    MatchedEvidence,
)
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.inference.providers.base import ModelCompletionRequest
from label_agent.retrieval.generative_domain_index import (
    DomainSearchHit,
)

logger = logging.getLogger(__name__)
_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


@dataclass(frozen=True)
class _Decision:
    match_status: Literal["matched", "ambiguous", "no_match"]
    entity_id: str | None
    confidence: float
    reason: str = ""


class EvidenceDomainIndex(Protocol):
    """S1/S2 候选索引协议；开发环境和生产服务使用不同实现。"""

    dictionary_snapshot_version: str

    async def top_k(self, query_text: str, k: int = 5) -> list[DomainSearchHit]:
        """返回未按 canonical_id 去重的候选。"""
        ...

    def find_exact(self, text: str) -> list[DomainSearchHit]:
        """返回标题精确匹配候选；远程实现可在 top_k 内完成并返回空列表。"""
        ...


class EvidenceCandidateMatcher:
    """每条证据独立检索和调用一次模型；仅 matched 结果参与合并。"""

    def __init__(
        self,
        *,
        domain: str,
        index: EvidenceDomainIndex,
        llm_gateway: LlmGateway,
        prompt_manager: PromptManager,
        prompt_version: str,
        audit_threshold: float = 0.85,
        top_k: int = 5,
    ) -> None:
        self._domain = domain
        self._index = index
        self._llm_gateway = llm_gateway
        self._prompt_manager = prompt_manager
        self._prompt_version = prompt_version
        self._audit_threshold = audit_threshold
        self._top_k = top_k

    async def match(
        self,
        evidence: list[CertificateEvidence],
        *,
        scene: str,
    ) -> EvidenceMatchingResult:
        selected: list[MatchedEvidence] = []
        decisions: list[EvidenceMatchDecision] = []
        unmatched_evidence: list[CertificateEvidence] = []
        snapshot_versions: set[str] = set()
        audit = 0

        for item in evidence:
            query = f"{item.title}\n{item.description}".strip()
            hits = self._merge_exact_title_first(
                item.title,
                await self._index.top_k(query, self._top_k),
            )
            snapshot_versions.update(
                hit.dictionary_snapshot_version
                for hit in hits
                if hit.dictionary_snapshot_version
            )
            if len(snapshot_versions) > 1:
                raise RetryableError(
                    "S1/S2 检索期间词典快照发生切换，请基于单一快照重试"
                )
            if not hits:
                unmatched_evidence.append(item)
                decisions.append(
                    EvidenceMatchDecision(
                        evidence_id=item.id,
                        match_status="no_match",
                        confidence=0.0,
                        reason="标准词典未召回候选",
                    )
                )
                audit = 1
                continue

            decision = await self._choose(item, hits, scene=scene)
            if decision is None:
                # 模型解析失败或返回 Top-5 之外的 ID：保留证据，但按需求不触发 audit。
                unmatched_evidence.append(item)
                continue

            if decision.match_status != "matched":
                unmatched_evidence.append(item)
                decisions.append(
                    EvidenceMatchDecision(
                        evidence_id=item.id,
                        match_status=decision.match_status,
                        confidence=decision.confidence,
                        reason=decision.reason,
                    )
                )
                audit = 1
                continue

            selected_hit = next(
                (hit for hit in hits if hit.item.id == decision.entity_id),
                None,
            )
            if selected_hit is None:
                unmatched_evidence.append(item)
                continue
            selected.append(
                MatchedEvidence(
                    entity_id=selected_hit.item.id,
                    canonical_id=selected_hit.item.resolved_canonical_id,
                    display_name=selected_hit.item.display_name,
                    evidence_id=item.id,
                    confidence=decision.confidence,
                )
            )
            decisions.append(
                EvidenceMatchDecision(
                    evidence_id=item.id,
                    match_status="matched",
                    entity_id=selected_hit.item.id,
                    canonical_id=selected_hit.item.resolved_canonical_id,
                    display_name=selected_hit.item.display_name,
                    confidence=decision.confidence,
                    reason=decision.reason,
                )
            )
            if decision.confidence < self._audit_threshold:
                audit = 1

        return EvidenceMatchingResult(
            matched=self._consolidate(selected),
            decisions=decisions,
            unmatched_evidence=unmatched_evidence,
            dictionary_snapshot_version=next(iter(snapshot_versions), ""),
            audit=audit,
        )

    def _merge_exact_title_first(
        self,
        title: str,
        hits: list[DomainSearchHit],
    ) -> list[DomainSearchHit]:
        """标题与正式名/别名精确命中时置顶，避免近义专精词条抢占 Top-1。"""
        exact_hits = self._index.find_exact(title)
        if not exact_hits:
            return hits
        merged: list[DomainSearchHit] = []
        seen: set[tuple[str, str]] = set()
        for hit in [*exact_hits, *hits]:
            key = (hit.item.id, hit.matched_text)
            if key in seen:
                continue
            seen.add(key)
            merged.append(hit)
            if len(merged) >= self._top_k:
                break
        return merged

    async def _choose(
        self,
        evidence: CertificateEvidence,
        hits: list[DomainSearchHit],
        *,
        scene: str,
    ) -> _Decision | None:
        entity_id_keys = {
            "career": "occupation_id",
            "certificate": "certificate_id",
        }
        try:
            entity_id_key = entity_id_keys[self._domain]
        except KeyError as exc:
            raise ValueError(f"不支持的证据匹配领域: {self._domain}") from exc
        candidates = [
            {
                **hit.item.resolved_metadata,
                entity_id_key: hit.item.id,
                "canonical_id": hit.item.resolved_canonical_id,
                "name": hit.item.display_name,
                "matched_text": hit.matched_text,
                "retrieval_score": round(hit.score, 6),
            }
            for hit in hits
        ]
        system_prompt, user_prompt = self._prompt_manager.render(
            scene=scene.lower(),
            prompt_version=self._prompt_version,
            variables={
                "evidence_json": json.dumps(evidence.model_dump(), ensure_ascii=False),
                "candidates_json": json.dumps(candidates, ensure_ascii=False),
            },
        )
        request = ModelCompletionRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema={"type": "object"},
            temperature=0.0,
            max_tokens=256,
        )
        result = await self._llm_gateway.complete(request)
        try:
            decision = self._parse_decision(result.raw_text, entity_id_key)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
            logger.warning("%s evidence=%s 选择结果解析失败: %s", scene, evidence.id, exc)
            return None

        if decision.match_status != "matched":
            if decision.match_status == "ambiguous" and self._domain != "certificate":
                logger.warning("%s evidence=%s 不支持 ambiguous", scene, evidence.id)
                return None
            return decision

        allowed_ids = {hit.item.id for hit in hits}
        if decision.entity_id not in allowed_ids:
            logger.warning(
                "%s evidence=%s 返回非法 ID=%s",
                scene,
                evidence.id,
                decision.entity_id,
            )
            return None
        return decision

    @staticmethod
    def _parse_decision(raw_text: str, entity_id_key: str) -> _Decision:
        text = (raw_text or "").strip()
        if not text:
            raise ValueError("空响应")
        match = _JSON_FENCE.search(text)
        if match:
            text = match.group(1).strip()
        payload: Any = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("根节点必须为对象")
        status = str(payload.get("match_status") or "matched").strip().lower()
        if status not in {"matched", "ambiguous", "no_match"}:
            raise ValueError("match_status 必须为 matched/ambiguous/no_match")
        match_status: Literal["matched", "ambiguous", "no_match"] = status  # type: ignore[assignment]
        confidence = float(payload["confidence"])
        if not 0.0 <= confidence <= 1.0:
            raise ValueError("confidence 必须在 0~1")
        reason = str(payload.get("reason") or "").strip()
        if match_status != "matched":
            return _Decision(
                match_status=match_status,
                entity_id=None,
                confidence=confidence,
                reason=reason,
            )
        entity_id = str(payload[entity_id_key]).strip()
        if not entity_id:
            raise ValueError(f"{entity_id_key} 不能为空")
        return _Decision(
            match_status=match_status,
            entity_id=entity_id,
            confidence=confidence,
            reason=reason,
        )

    @staticmethod
    def _consolidate(selected: list[MatchedEvidence]) -> list[ConsolidatedMatch]:
        by_canonical_id: dict[str, ConsolidatedMatch] = {}
        for item in selected:
            existing = by_canonical_id.get(item.canonical_id)
            evidence = EvidenceConfidence(id=item.evidence_id, confidence=item.confidence)
            if existing is None:
                by_canonical_id[item.canonical_id] = ConsolidatedMatch(
                    entity_id=item.entity_id,
                    canonical_id=item.canonical_id,
                    display_name=item.display_name,
                    evidences=[evidence],
                )
                continue
            if evidence.id not in {ref.id for ref in existing.evidences}:
                existing.evidences.append(evidence)
        return list(by_canonical_id.values())[:5]
