"""S4 独立场景装配，不加载 S1/S2 文档解析依赖。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from label_agent.inference.embeddings.base import EmbeddingProvider
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.product_labeling import ProductLabelingInference
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.infrastructure.milvus_proxy.client import MilvusProxyClient
from label_agent.infrastructure.taxonomy.product_taxonomy import ProductTaxonomyImporter
from label_agent.perception.image.ocr import OcrEngine
from label_agent.perception.media_guard import MediaGuard
from label_agent.retrieval.product_category_retriever import (
    ProductCategoryRetriever,
    ProductCategorySearch,
)
from label_agent.retrieval.product_category_vector_retriever import (
    ProductCategoryVectorRetriever,
)
from label_agent.scenarios.s4_product.handler import S4ProductHandler
from label_agent.scenarios.s4_product.perception import ProductPerceptionService
from label_agent.scenarios.s4_product.pipeline import S4ProductPipeline

REPO_ROOT = Path(__file__).resolve().parents[3]


async def build_s4_handler(
    llm_gateway: LlmGateway,
    embedding_provider: EmbeddingProvider,
    yaml_config: dict[str, Any],
    *,
    prompt_manager: PromptManager | None = None,
    taxonomy_path: str | Path | None = None,
    milvus_proxy: MilvusProxyClient | None = None,
) -> S4ProductHandler:
    """装配 S4；本地使用工作簿，生产可切换服务端类目向量库。"""
    prompts = prompt_manager or PromptManager()
    scene_cfg = (yaml_config.get("scene") or {}).get("s4") or {}
    policy_cfg = (yaml_config.get("policy") or {}).get("s4") or {}
    vector_cfg = yaml_config.get("vector") or {}
    inference_cfg = yaml_config.get("inference") or {}
    prompt_versions = inference_cfg.get("prompt_versions") or {}
    top_k = int(policy_cfg.get("retrieval_top_k", 20))
    backend = os.getenv(
        "S4_CATEGORY_RETRIEVAL_BACKEND",
        str(scene_cfg.get("category_retrieval_backend") or "local"),
    ).lower()
    retriever: ProductCategorySearch
    if backend == "milvus":
        if milvus_proxy is None:
            raise ValueError("S4 使用 milvus 召回时必须注入 MilvusProxyClient")
        taxonomy_version = os.getenv(
            "S4_TAXONOMY_VERSION",
            str(scene_cfg.get("taxonomy_version") or ""),
        ).strip()
        collection = os.getenv(
            "S4_CATEGORY_VECTOR_COLLECTION",
            str(vector_cfg.get("product_category_collection") or "product_category_vectors"),
        )
        retriever = ProductCategoryVectorRetriever(
            embedding_provider,
            milvus_proxy,
            collection=collection,
            taxonomy_version=taxonomy_version,
            top_k=top_k,
        )
    elif backend == "local":
        configured_path = str(
            scene_cfg.get("taxonomy_path") or "docs/在场电商平台商品分类信息.xlsx"
        )
        resolved_path = Path(taxonomy_path or configured_path)
        if not resolved_path.is_absolute():
            resolved_path = REPO_ROOT / resolved_path
        taxonomy_importer = ProductTaxonomyImporter()
        taxonomy = taxonomy_importer.load(resolved_path)
        if bool(scene_cfg.get("persist_snapshot", False)):
            snapshot_dir = Path(str(scene_cfg.get("snapshot_dir") or "var/taxonomy"))
            if not snapshot_dir.is_absolute():
                snapshot_dir = REPO_ROOT / snapshot_dir
            taxonomy_importer.persist_snapshot(taxonomy, snapshot_dir)
        local_retriever = ProductCategoryRetriever(
            taxonomy,
            embedding_provider,
            top_k=top_k,
            rrf_k=int(policy_cfg.get("rrf_k", 60)),
        )
        await local_retriever.build()
        retriever = local_retriever
    else:
        raise ValueError(f"不支持的 S4 类目召回后端: {backend}")

    allowed_domains = set(str(item) for item in (scene_cfg.get("media_allowed_domains") or []))
    allowed_domains.update(
        item.strip()
        for item in os.getenv("S4_MEDIA_ALLOWED_DOMAINS", "").split(",")
        if item.strip()
    )
    media_guard = MediaGuard(
        allowed_domains=allowed_domains,
        max_bytes=int(scene_cfg.get("max_image_bytes", 20 * 1024 * 1024)),
    )
    classifier_alias = str(scene_cfg.get("classifier_model_alias") or "primary")
    reviewer_alias = str(scene_cfg.get("reviewer_model_alias") or "reviewer")
    configured_models = {
        str(item.get("alias")): str(item.get("model_name"))
        for item in (inference_cfg.get("models") or [])
    }
    classifier_model = configured_models.get(classifier_alias)
    reviewer_model = configured_models.get(reviewer_alias)
    if classifier_model and reviewer_model and classifier_model == reviewer_model:
        raise ValueError("S4 classifier 与 reviewer 必须配置为不同 model_name")

    inference = ProductLabelingInference(
        llm_gateway,
        prompts,
        classifier_alias=classifier_alias,
        reviewer_alias=reviewer_alias,
        analysis_prompt=str(prompt_versions.get("s4_analysis") or "s4-analysis-v1"),
        classifier_prompt=str(prompt_versions.get("s4_classifier") or "s4-classify-v1"),
        reviewer_prompt=str(prompt_versions.get("s4_reviewer") or "s4-review-v1"),
        search_prompt=str(prompt_versions.get("s4_search") or "s4-search-v1"),
        suggestion_prompt=str(prompt_versions.get("s4_suggestion") or "s4-suggest-v1"),
    )
    pipeline = S4ProductPipeline(
        perception=ProductPerceptionService(
            llm_gateway,
            prompts,
            OcrEngine(),
            media_guard,
            vision_prompt_version=str(prompt_versions.get("s4_vision") or "s4-vision-v1"),
            max_images=int(scene_cfg.get("max_images", 5)),
        ),
        retriever=retriever,
        inference=inference,
        auto_pass_threshold=float(policy_cfg.get("auto_pass_threshold", 0.85)),
    )
    return S4ProductHandler(pipeline)
