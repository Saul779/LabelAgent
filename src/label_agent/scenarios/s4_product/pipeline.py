"""S4 商品打标固定管线。"""

from __future__ import annotations

from typing import Literal

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.s4_product import ProductCategoryCandidate
from label_agent.domain.models.s4_result import (
    ProductCategoryPath,
    ProductCategoryRef,
    ProductLabelResult,
    ProductModelRun,
)
from label_agent.inference.product_labeling import ProductLabelingInference
from label_agent.retrieval.product_category_retriever import ProductCategorySearch
from label_agent.scenarios.s4_product.perception import ProductPerceptionService


class S4ProductPipeline:
    """感知 → L2 混合召回 → 模型 A → 模型 B → 规则决策 → 搜索词。"""

    def __init__(
        self,
        perception: ProductPerceptionService,
        retriever: ProductCategorySearch,
        inference: ProductLabelingInference,
        *,
        auto_pass_threshold: float = 0.85,
    ) -> None:
        self._perception = perception
        self._retriever = retriever
        self._inference = inference
        self._threshold = auto_pass_threshold

    async def run(self, ctx: JobContext) -> ProductLabelResult:
        perception = await self._perception.perceive(ctx)
        analysis = await self._inference.analyze(perception)
        candidates = await self._retriever.retrieve(analysis.retrieval_text(perception.title))
        classifier = await self._inference.classify(analysis, candidates, title=perception.title)
        reviewer = await self._inference.review(
            analysis,
            candidates,
            selected_level2_id=classifier.level2_category_id,
            title=perception.title,
        )

        by_id = {item.category.category_id: item for item in candidates}
        classifier_candidate = by_id.get(classifier.level2_category_id or "")
        reviewer_candidate = by_id.get(reviewer.level2_category_id or "")
        reason_codes = _unique(classifier.reason_codes + reviewer.reason_codes)
        degraded = []
        if perception.failed_image_refs:
            degraded.append("image")

        classifier_valid = classifier.decision == "classified" and classifier_candidate is not None
        reviewer_valid = reviewer.decision == "classified" and reviewer_candidate is not None
        both_unknown = classifier.decision == "unknown" and reviewer.decision == "unknown"
        same_category = (
            classifier_valid
            and reviewer_valid
            and classifier.level2_category_id == reviewer.level2_category_id
        )
        parent_valid = bool(
            classifier_candidate
            and classifier_candidate.category.level == 2
            and classifier_candidate.category.parent_category_id
            and classifier_candidate.category.parent_category_name
        )
        confidence = min(classifier.confidence, reviewer.confidence)

        if classifier.decision == "classified" and not classifier_valid:
            reason_codes.append("INVALID_CLASSIFIER_CATEGORY_ID")
        if reviewer.decision == "classified" and not reviewer_valid:
            reason_codes.append("INVALID_REVIEWER_CATEGORY_ID")
        if not parent_valid and classifier_candidate is not None:
            reason_codes.append("INVALID_CATEGORY_PARENT")
        if analysis.modality_conflict:
            reason_codes.append("TITLE_IMAGE_CONFLICT")
        if degraded:
            reason_codes.append("DEGRADED_PERCEPTION")

        critical_degradation = bool(perception.failed_image_refs) and not any(
            item.ocr_succeeded or item.vision_succeeded for item in perception.images
        )
        blocking_rule_hit = _exclusion_rule_hit(
            classifier_candidate, analysis.retrieval_text(perception.title)
        )
        if blocking_rule_hit:
            reason_codes.append("EXCLUSION_RULE_HIT")
        if {"EXCLUSION_RULE_HIT", "CATEGORY_BOUNDARY_AMBIGUOUS"}.intersection(reason_codes):
            blocking_rule_hit = True
        can_auto_pass = (
            same_category
            and parent_valid
            and confidence >= self._threshold
            and not analysis.modality_conflict
            and not critical_degradation
            and not blocking_rule_hit
        )

        decision: Literal["classified", "unknown", "need_review"]
        selected: ProductCategoryCandidate | None = classifier_candidate
        suggestion = None
        search_terms = None
        if can_auto_pass:
            decision = "classified"
            assert selected is not None
            search_terms = await self._inference.generate_search_terms(
                analysis, selected, title=perception.title
            )
        elif both_unknown:
            decision = "unknown"
            selected = None
            reason_codes.append("NO_MATCHING_CATEGORY")
            try:
                suggestion = await self._inference.suggest_category(
                    analysis, title=perception.title
                )
            except NonRetryableError:
                # 类目建议是 unknown 的可选旁路，不应反向破坏已完成的业务判断。
                reason_codes.append("CATEGORY_SUGGESTION_UNAVAILABLE")
        else:
            decision = "need_review"
            if not same_category:
                reason_codes.append("MODEL_DISAGREEMENT")
            if confidence < self._threshold:
                reason_codes.append("LOW_CONFIDENCE")

        category_path = self._category_path(selected)
        evidence_refs = (["title"] if perception.title else []) + [
            f"image:{item.asset_id}" for item in perception.images
        ]
        reason = _reason_text(
            decision=decision,
            classifier_reason=classifier.reason,
            reviewer_reason=reviewer.reason,
            conflict=analysis.conflict_description,
        )
        return ProductLabelResult(
            product_id=str(ctx.payload.get("product_id") or ctx.biz_id),
            taxonomy_version=self._retriever.taxonomy_version,
            category=category_path,
            confidence=confidence,
            decision=decision,
            need_manual_review=decision != "classified",
            reason_codes=_unique(reason_codes),
            reason=reason,
            evidence_refs=evidence_refs,
            search_terms=search_terms,
            category_suggestion=suggestion,
            model_runs={
                "classifier": ProductModelRun(
                    model_name=classifier.model_name,
                    model_alias=self._inference.classifier_alias,
                    prompt_version=self._inference.classifier_prompt,
                    confidence=classifier.confidence,
                    decision=classifier.decision,
                    level2_category_id=classifier.level2_category_id,
                ),
                "reviewer": ProductModelRun(
                    model_name=reviewer.model_name,
                    model_alias=self._inference.reviewer_alias,
                    prompt_version=self._inference.reviewer_prompt,
                    confidence=reviewer.confidence,
                    decision=reviewer.decision,
                    level2_category_id=reviewer.level2_category_id,
                ),
            },
            degraded_modalities=degraded,
        )

    def _category_path(
        self, candidate: ProductCategoryCandidate | None
    ) -> ProductCategoryPath | None:
        if candidate is None:
            return None
        child = candidate.category
        if not child.parent_category_id or not child.parent_category_name:
            return None
        return ProductCategoryPath(
            level1=ProductCategoryRef(
                category_id=child.parent_category_id,
                name=child.parent_category_name,
            ),
            level2=ProductCategoryRef(category_id=child.category_id, name=child.category_name),
        )


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _reason_text(
    *, decision: str, classifier_reason: str, reviewer_reason: str, conflict: str
) -> str:
    parts = [f"decision={decision}"]
    if classifier_reason:
        parts.append(f"classifier: {classifier_reason}")
    if reviewer_reason:
        parts.append(f"reviewer: {reviewer_reason}")
    if conflict:
        parts.append(f"conflict: {conflict}")
    return "; ".join(parts)


def _exclusion_rule_hit(candidate: ProductCategoryCandidate | None, evidence_text: str) -> bool:
    if candidate is None:
        return False
    compact = "".join(evidence_text.lower().split())
    return any(
        "".join(keyword.lower().split()) in compact
        for keyword in candidate.category.negative_keywords
        if keyword.strip()
    )
