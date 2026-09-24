"""S4 真实装配闭环：Prompt/双模型 alias/召回/结果契约。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from label_agent.bootstrap.s4_scene_factory import build_s4_handler
from label_agent.core.context import JobContext
from label_agent.inference.providers.base import ModelCompletionResult
from label_agent.infrastructure.taxonomy.product_taxonomy import ProductTaxonomyImporter

_WORKBOOK = Path(__file__).resolve().parents[3] / "docs" / "在场电商平台商品分类信息.xlsx"


class _Embedding:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float("水果" in text), 1.0] for text in texts]


class _MilvusProxy:
    def __init__(self, category_id: str) -> None:
        self.category_id = category_id
        self.calls = 0

    async def search(self, collection, query_vector, top_k, filters):
        self.calls += 1
        assert collection == "product_category_vectors"
        assert query_vector
        assert top_k == 20
        assert filters["taxonomy_version"] == "taxonomy-prod-v1"
        return [
            {
                "id": self.category_id,
                "score": 0.95,
                "metadata": {
                    "category_id": self.category_id,
                    "category_name": "水果",
                    "level": 2,
                    "parent_category_id": "category-food",
                    "parent_category_name": "食品生鲜",
                    "taxonomy_version": "taxonomy-prod-v1",
                    "status": "active",
                    "positive_keywords": ["苹果"],
                    "negative_keywords": ["水果刀"],
                },
            }
        ]


class _Gateway:
    def __init__(self, category_id: str) -> None:
        self.category_id = category_id
        self.aliases: list[str | None] = []

    async def complete(self, request, model_alias=None):
        self.aliases.append(model_alias)
        if "商品分析专家" in request.system_prompt:
            payload = {
                "product_name": "苹果",
                "product_type": "水果",
                "brand": "",
                "attributes": ["新鲜"],
                "usage": "食用",
                "image_features": [],
                "keywords": ["水果", "苹果"],
                "summary": "新鲜苹果",
                "modality_conflict": False,
                "conflict_description": "",
            }
            model_name = "model-a"
        elif "独立的电商分类审核模型" in request.system_prompt:
            payload = {
                "decision": "classified",
                "level2_category_id": self.category_id,
                "confidence": 0.91,
                "reason": "复核一致",
                "reason_codes": [],
            }
            model_name = "model-b"
        elif "电商商品分类专家" in request.system_prompt:
            payload = {
                "decision": "classified",
                "level2_category_id": self.category_id,
                "confidence": 0.93,
                "reason": "主体是水果",
                "reason_codes": [],
                "matched_features": ["苹果"],
            }
            model_name = "model-a"
        else:
            payload = {
                "core_terms": ["苹果", "新鲜苹果"],
                "attribute_terms": ["新鲜"],
                "scene_terms": [],
                "long_tail_queries": [],
                "synonym_terms": [],
                "feature_terms": [],
                "search_summary": "苹果商品搜索词",
                "keyword_quality_score": 0.9,
            }
            model_name = "model-a"
        return ModelCompletionResult(
            raw_text=json.dumps(payload, ensure_ascii=False),
            model_name=model_name,
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
        )


def test_factory_uses_distinct_reviewer_alias_and_completes_title_only_product() -> None:
    taxonomy = ProductTaxonomyImporter().load(_WORKBOOK)
    child = next(item for item in taxonomy.level2 if item.category_name == "水果")
    gateway = _Gateway(child.category_id)
    config = {
        "scene": {
            "s4": {
                "classifier_model_alias": "primary",
                "reviewer_model_alias": "reviewer",
                "max_images": 5,
            }
        },
        "policy": {"s4": {"auto_pass_threshold": 0.85, "retrieval_top_k": 20}},
        "inference": {
            "models": [
                {"alias": "primary", "model_name": "model-a"},
                {"alias": "reviewer", "model_name": "model-b"},
            ]
        },
    }
    handler = asyncio.run(
        build_s4_handler(
            gateway,  # type: ignore[arg-type]
            _Embedding(),  # type: ignore[arg-type]
            config,
            taxonomy_path=_WORKBOOK,
        )
    )
    result = asyncio.run(
        handler.run(
            JobContext(
                job_id="job-s4-factory",
                task_id="task-s4-factory",
                scene="S4",
                biz_id="product-factory",
                payload={"product_id": "product-factory", "title": "新鲜苹果水果"},
            )
        )
    )

    assert result.decision == "classified"
    assert result.category is not None
    assert result.category.level2.name == "水果"
    assert gateway.aliases == ["primary", "primary", "reviewer", "primary"]
    assert result.model_runs["classifier"].model_name == "model-a"
    assert result.model_runs["reviewer"].model_name == "model-b"


def test_factory_uses_remote_category_vectors_without_loading_workbook() -> None:
    category_id = "category-fruit"
    gateway = _Gateway(category_id)
    proxy = _MilvusProxy(category_id)
    config = {
        "scene": {
            "s4": {
                "category_retrieval_backend": "milvus",
                "taxonomy_version": "taxonomy-prod-v1",
                "classifier_model_alias": "primary",
                "reviewer_model_alias": "reviewer",
            }
        },
        "policy": {"s4": {"auto_pass_threshold": 0.85, "retrieval_top_k": 20}},
        "vector": {"product_category_collection": "product_category_vectors"},
        "inference": {
            "models": [
                {"alias": "primary", "model_name": "model-a"},
                {"alias": "reviewer", "model_name": "model-b"},
            ]
        },
    }
    handler = asyncio.run(
        build_s4_handler(
            gateway,  # type: ignore[arg-type]
            _Embedding(),  # type: ignore[arg-type]
            config,
            taxonomy_path="missing.xlsx",
            milvus_proxy=proxy,  # type: ignore[arg-type]
        )
    )

    result = asyncio.run(
        handler.run(
            JobContext(
                job_id="job-s4-remote",
                task_id="task-s4-remote",
                scene="S4",
                biz_id="product-remote",
                payload={"product_id": "product-remote", "title": "新鲜苹果水果"},
            )
        )
    )

    assert result.decision == "classified"
    assert result.taxonomy_version == "taxonomy-prod-v1"
    assert result.category is not None
    assert result.category.level1.name == "食品生鲜"
    assert proxy.calls == 1
