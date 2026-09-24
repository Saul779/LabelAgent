"""置信度策略接口（§7.2，D001）。

完整规则引擎处于 [暂定] 状态；实现必须支持按 policy_version 切换与历史回放，
系数/阈值一律通过配置中心加载，禁止写入代码常量。
"""

from __future__ import annotations

from typing import Protocol

from label_agent.domain.models.evidence import EvidenceBundle
from label_agent.domain.models.proposal import SemanticProposal


class FinalConfidence:
    """保留原始模型分数与各系数，不在计算中提前舍入。"""

    def __init__(
        self,
        calibrated_model_score: float,
        evidence_factor: float,
        consistency_factor: float,
        stability_factor: float,
    ) -> None:
        """保存校准后的模型分与证据/一致性/稳定性系数，供 value 合成最终置信度。"""
        self.calibrated_model_score = calibrated_model_score
        self.evidence_factor = evidence_factor
        self.consistency_factor = consistency_factor
        self.stability_factor = stability_factor

    @property
    def value(self) -> float:
        """最终置信度 = 校准模型分 × min(证据/一致性/稳定性系数)。"""
        return self.calibrated_model_score * min(
            self.evidence_factor, self.consistency_factor, self.stability_factor
        )


class ConfidencePolicy(Protocol):
    """置信度策略：把模型分/检索分合成为最终置信度。"""

    policy_version: str

    def score(self, proposal: SemanticProposal, evidence: EvidenceBundle) -> FinalConfidence: ...


class ConfidencePolicyRegistry:
    """按 policy_version 注册/解析实现，支持历史 Job 按记录版本重新评估（回放）。"""

    def __init__(self) -> None:
        """初始化策略注册表。"""
        self._policies: dict[str, ConfidencePolicy] = {}

    def register(self, policy: ConfidencePolicy) -> None:
        """按版本注册置信度策略。"""
        self._policies[policy.policy_version] = policy

    def resolve(self, policy_version: str) -> ConfidencePolicy:
        """按版本解析置信度策略。"""
        try:
            return self._policies[policy_version]
        except KeyError as exc:
            raise ValueError(f"未注册的 policy_version: {policy_version}") from exc
