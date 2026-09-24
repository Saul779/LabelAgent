"""默认候选置信度公式（§7.2，标记为候选而非定稿）。

Final_Conf = calibrated_model_score × min(evidence_factor, consistency_factor, stability_factor)

系数来源于配置中心（此处仅定义计算逻辑，系数加载见 validation/rule_engine）。
"""

from __future__ import annotations

from label_agent.domain.models.evidence import EvidenceBundle
from label_agent.domain.models.proposal import SemanticProposal
from label_agent.domain.policies.confidence_policy import ConfidencePolicy, FinalConfidence


class ProvisionalRuleMvp1(ConfidencePolicy):
    """MVP 临时置信度规则实现。"""

    policy_version = "provisional-rule-mvp-1"

    def __init__(
        self,
        evidence_factor: float,
        consistency_factor: float,
        stability_factor: float,
    ) -> None:
        """加载 MVP 规则参数。"""
        self._evidence_factor = evidence_factor
        self._consistency_factor = consistency_factor
        self._stability_factor = stability_factor

    def score(self, proposal: SemanticProposal, evidence: EvidenceBundle) -> FinalConfidence:
        """按规则计算最终置信度分。"""
        calibrated_score = max((t.model_score for t in proposal.tags), default=0.0)
        return FinalConfidence(
            calibrated_model_score=calibrated_score,
            evidence_factor=self._evidence_factor,
            consistency_factor=self._consistency_factor,
            stability_factor=self._stability_factor,
        )
