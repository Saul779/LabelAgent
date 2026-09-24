"""S4 商品理解、双模型分类、搜索词与类目建议的模型调用封装。"""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.s4_product import (
    ProductAnalysis,
    ProductCategoryCandidate,
    ProductClassificationDecision,
    ProductPerception,
    ProductReviewDecision,
)
from label_agent.domain.models.s4_result import (
    ProductCategorySuggestion,
    ProductSearchTerms,
)
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.inference.providers.base import ModelCompletionRequest, ModelCompletionResult

_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
_T = TypeVar("_T", bound=BaseModel)


class S4ModelOutputError(NonRetryableError):
    error_code = "S4_MODEL_OUTPUT_INVALID"


class _SuggestionEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category_suggestion: ProductCategorySuggestion | None = None


class ProductLabelingInference:
    """所有 S4 LLM 调用的唯一业务入口。"""

    def __init__(
        self,
        llm_gateway: LlmGateway,
        prompt_manager: PromptManager,
        *,
        classifier_alias: str,
        reviewer_alias: str,
        analysis_prompt: str = "s4-analysis-v1",
        classifier_prompt: str = "s4-classify-v1",
        reviewer_prompt: str = "s4-review-v1",
        search_prompt: str = "s4-search-v1",
        suggestion_prompt: str = "s4-suggest-v1",
    ) -> None:
        if classifier_alias == reviewer_alias:
            raise ValueError("S4 classifier 与 reviewer 必须使用不同模型 alias")
        self._llm_gateway = llm_gateway
        self._prompts = prompt_manager
        self.classifier_alias = classifier_alias
        self.reviewer_alias = reviewer_alias
        self.analysis_prompt = analysis_prompt
        self.classifier_prompt = classifier_prompt
        self.reviewer_prompt = reviewer_prompt
        self.search_prompt = search_prompt
        self.suggestion_prompt = suggestion_prompt

    async def analyze(self, perception: ProductPerception) -> ProductAnalysis:
        payload = {
            "title": perception.title,
            "images": [
                {
                    "asset_id": item.asset_id,
                    "ocr_text": item.ocr_text,
                    "vision_text": item.vision_text,
                }
                for item in perception.images
            ],
        }
        model, _ = await self._complete_model(
            prompt_version=self.analysis_prompt,
            variables={"product_evidence": _json(payload)},
            model_alias=self.classifier_alias,
            model_type=ProductAnalysis,
            max_tokens=1400,
        )
        return model

    async def classify(
        self,
        analysis: ProductAnalysis,
        candidates: list[ProductCategoryCandidate],
        *,
        title: str,
    ) -> ProductClassificationDecision:
        model, result = await self._complete_model(
            prompt_version=self.classifier_prompt,
            variables={
                "product_title": title,
                "product_analysis": _json(analysis.model_dump(mode="json")),
                "candidate_categories": _json(_candidate_payload(candidates)),
            },
            model_alias=self.classifier_alias,
            model_type=ProductClassificationDecision,
            max_tokens=1200,
        )
        return model.model_copy(update={"model_name": result.model_name})

    async def review(
        self,
        analysis: ProductAnalysis,
        candidates: list[ProductCategoryCandidate],
        *,
        selected_level2_id: str | None,
        title: str,
    ) -> ProductReviewDecision:
        selected = next(
            (
                item.category
                for item in candidates
                if item.category.category_id == selected_level2_id
            ),
            None,
        )
        selected_payload: dict[str, Any] | str = "unknown"
        if selected is not None:
            selected_payload = {
                "level2_category_id": selected.category_id,
                "category_path": selected.path,
            }
        # 刻意不传模型 A 的置信度、原因和 matched_features，避免复核锚定。
        model, result = await self._complete_model(
            prompt_version=self.reviewer_prompt,
            variables={
                "product_title": title,
                "product_analysis": _json(analysis.model_dump(mode="json")),
                "selected_category": _json(selected_payload),
                "candidate_categories": _json(_candidate_payload(candidates)),
            },
            model_alias=self.reviewer_alias,
            model_type=ProductReviewDecision,
            max_tokens=1200,
        )
        return model.model_copy(update={"model_name": result.model_name})

    async def generate_search_terms(
        self,
        analysis: ProductAnalysis,
        category: ProductCategoryCandidate,
        *,
        title: str,
    ) -> ProductSearchTerms:
        model, _ = await self._complete_model(
            prompt_version=self.search_prompt,
            variables={
                "product_title": title,
                "product_analysis": _json(analysis.model_dump(mode="json")),
                "category_information": _json(
                    {
                        "category_id": category.category.category_id,
                        "category_path": category.category.path,
                        "description": category.category.category_description,
                    }
                ),
            },
            model_alias=self.classifier_alias,
            model_type=ProductSearchTerms,
            max_tokens=1800,
        )
        return _sanitize_search_terms(model)

    async def suggest_category(
        self,
        analysis: ProductAnalysis,
        *,
        title: str,
    ) -> ProductCategorySuggestion | None:
        model, _ = await self._complete_model(
            prompt_version=self.suggestion_prompt,
            variables={
                "product_title": title,
                "product_analysis": _json(analysis.model_dump(mode="json")),
            },
            model_alias=self.classifier_alias,
            model_type=_SuggestionEnvelope,
            max_tokens=800,
        )
        return model.category_suggestion

    async def _complete_model(
        self,
        *,
        prompt_version: str,
        variables: dict[str, Any],
        model_alias: str,
        model_type: type[_T],
        max_tokens: int,
    ) -> tuple[_T, ModelCompletionResult]:
        result = await self._complete_json(
            prompt_version=prompt_version,
            variables=variables,
            model_alias=model_alias,
            max_tokens=max_tokens,
        )
        try:
            return model_type.model_validate(_loads_json(result.raw_text)), result
        except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as first_error:
            retry = await self._complete_json(
                prompt_version=prompt_version,
                variables=variables,
                model_alias=model_alias,
                max_tokens=max_tokens,
                correction=(
                    f"上次输出不符合 {model_type.__name__} 的字段和类型约束："
                    f"{first_error}。请修正并只输出合法 JSON。"
                ),
            )
            try:
                return model_type.model_validate(_loads_json(retry.raw_text)), retry
            except (ValidationError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise S4ModelOutputError(
                    f"S4 模型连续两次输出不符合 {model_type.__name__}: {exc}"
                ) from exc

    async def _complete_json(
        self,
        *,
        prompt_version: str,
        variables: dict[str, Any],
        model_alias: str,
        max_tokens: int,
        correction: str = "",
    ) -> ModelCompletionResult:
        system_prompt, user_prompt = self._prompts.render(
            scene="s4", prompt_version=prompt_version, variables=variables
        )
        if correction:
            system_prompt = f"{system_prompt}\n{correction}"
        request = ModelCompletionRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema={"type": "object"},
            temperature=0.0,
            max_tokens=max_tokens,
        )
        first = await self._llm_gateway.complete(request, model_alias=model_alias)
        try:
            _loads_json(first.raw_text)
            return first
        except (json.JSONDecodeError, ValueError):
            retry = request.model_copy(
                update={
                    "system_prompt": system_prompt
                    + "\n上次输出不是合法 JSON。请仅返回一个符合字段约束的 JSON 对象。"
                }
            )
            second = await self._llm_gateway.complete(retry, model_alias=model_alias)
            try:
                _loads_json(second.raw_text)
            except (json.JSONDecodeError, ValueError) as exc:
                raise S4ModelOutputError(f"S4 模型连续两次返回非法 JSON: {exc}") from exc
            return second


def _candidate_payload(candidates: list[ProductCategoryCandidate]) -> list[dict[str, Any]]:
    return [
        {
            "level2_category_id": item.category.category_id,
            "parent_category_id": item.category.parent_category_id,
            "category_path": item.category.path,
            "category_description": item.category.category_description,
            "include_products": item.category.include_products,
            "exclude_products": item.category.exclude_products,
            "positive_keywords": item.category.positive_keywords,
            "negative_keywords": item.category.negative_keywords,
        }
        for item in candidates
    ]


def _loads_json(raw_text: str) -> dict[str, Any]:
    text = raw_text.strip()
    match = _JSON_FENCE.search(text)
    if match:
        text = match.group(1)
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("模型输出必须是 JSON 对象")
    return payload


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _sanitize_search_terms(terms: ProductSearchTerms) -> ProductSearchTerms:
    banned = ("世界第一", "绝对最好", "顶级", "百分百", "全网最低")

    def clean(values: list[str]) -> list[str]:
        result: list[str] = []
        for value in values:
            normalized = " ".join(value.split()).strip()
            if not normalized or any(word in normalized for word in banned):
                continue
            if normalized not in result:
                result.append(normalized)
        return result

    return terms.model_copy(
        update={
            "core_terms": clean(terms.core_terms),
            "attribute_terms": clean(terms.attribute_terms),
            "scene_terms": clean(terms.scene_terms),
            "long_tail_queries": clean(terms.long_tail_queries),
            "synonym_terms": clean(terms.synonym_terms),
            "feature_terms": clean(terms.feature_terms),
        }
    )
