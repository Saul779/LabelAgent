"""PreValidation：整单写前校验，必须在任何 Tag Service 写入之前通过（§5.1.1、§7.1）。

当前覆盖 EvidenceRef 可回查、新标签命名与安全、模态失败记录完整性；
ID 合法性及 canonical 去重由前置 EntityResolver 负责。
"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NonRetryableError
from label_agent.validation.evidence_ref_validator import validate_all
from label_agent.validation.new_tag_safety import assert_new_tag_safe
from label_agent.validation.safety.injection_detector import InjectionDetector
from label_agent.validation.safety.pii_detector import PiiDetector
from label_agent.validation.safety.sensitive_word_filter import SensitiveWordFilter


class PreValidator:
    """写入前整单校验：证据、新标签安全与模态完整性门禁。"""

    def __init__(
        self,
        sensitive_word_filter: SensitiveWordFilter,
        pii_detector: PiiDetector,
        injection_detector: InjectionDetector,
        *,
        allowed_domains: set[str],
    ) -> None:
        """注入预校验规则依赖。"""
        self._sensitive_word_filter = sensitive_word_filter
        self._pii_detector = pii_detector
        self._injection_detector = injection_detector
        self._allowed_domains = allowed_domains

    def validate(self, ctx: JobContext) -> None:
        """在写入前完成整单模态、证据引用与新标签安全校验。"""
        if ctx.semantic_proposal is None:
            raise NonRetryableError("PreValidation 之前必须先完成语义提议与实体解析阶段")
        self._validate_modality_completeness(ctx)
        self._validate_evidence_refs(ctx)
        self._validate_new_tags(ctx)

    def _validate_evidence_refs(self, ctx: JobContext) -> None:
        """批量校验最终分类与标签提议携带的证据引用。"""
        proposal = ctx.semantic_proposal
        if proposal is None:
            raise NonRetryableError("PreValidation 之前必须先完成语义提议与实体解析阶段")
        refs = []
        if proposal.primary_category is not None:
            refs.extend(proposal.primary_category.evidence_refs)
        if proposal.secondary_category is not None:
            refs.extend(proposal.secondary_category.evidence_refs)
        for tag in ctx.resolved_entities:
            refs.extend(tag.evidence_refs)
        if refs:
            validate_all(ctx, refs)

    def _validate_new_tags(self, ctx: JobContext) -> None:
        """整单检查所有待创建标签，确保写入开始前已通过安全门禁。"""
        for proposal in ctx.resolved_entities:
            request = proposal.new_tag_request
            if request is None:
                continue
            assert_new_tag_safe(
                request.proposed_name,
                request.domain,
                allowed_domains=self._allowed_domains,
                sensitive_word_filter=self._sensitive_word_filter,
                pii_detector=self._pii_detector,
                injection_detector=self._injection_detector,
            )

    def _validate_modality_completeness(self, ctx: JobContext) -> None:
        """检查必需模态是否齐全，不齐则标记降级或拒绝。"""
        if ctx.content_bundle is None:
            return
        for modality in ctx.content_bundle.failed_modalities:
            if modality not in ctx.degraded_modalities:
                raise NonRetryableError(f"模态失败未记录到 degraded_modalities: {modality}")
