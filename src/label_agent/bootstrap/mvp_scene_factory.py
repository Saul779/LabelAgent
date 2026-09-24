"""S1/S2/S3/S4/T1 MVP 场景装配，供 JobWorker 与本地脚本共用。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from label_agent.bootstrap.inference_factory import (
    build_embedding_provider,
    build_llm_gateway,
    load_yaml_config,
    require_openai_api_key,
)
from label_agent.bootstrap.s4_scene_factory import build_s4_handler
from label_agent.inference.embeddings.openai_embedding_provider import OpenAiEmbeddingProvider
from label_agent.inference.generative_proposer import GenerativeProposer
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.inference.semantic_proposer import SemanticProposer
from label_agent.inference.t1_task_detail import T1TaskDetailInference
from label_agent.infrastructure.milvus_proxy.client import MilvusProxyClient
from label_agent.infrastructure.tag_service.client import TagServiceClient
from label_agent.infrastructure.tag_service.fixture_client import FixtureTagServiceClient
from label_agent.perception.asr.transcriber import AsrTranscriber
from label_agent.perception.certificate_content_loader import CertificateContentLoader
from label_agent.perception.content_bundle_builder import ContentBundleBuilder
from label_agent.perception.extractors.image_vision_extractor import ImageVisionExtractor
from label_agent.perception.image.ocr import OcrEngine
from label_agent.perception.media_guard import MediaGuard
from label_agent.perception.t1_content_loader import T1ContentLoader
from label_agent.perception.text.normalizer import TextNormalizer
from label_agent.perception.video.frame_sampler import VideoFrameSampler
from label_agent.resolution.entity_resolver import EntityResolver
from label_agent.resolution.evidence_candidate_matcher import (
    EvidenceCandidateMatcher,
    EvidenceDomainIndex,
)
from label_agent.resolution.tag_committer import TagCommitter
from label_agent.retrieval.candidate_retriever import CandidateRetriever
from label_agent.retrieval.generative_domain_index import InMemoryDomainVectorIndex
from label_agent.retrieval.matchers.alias_match import AliasMatcher
from label_agent.retrieval.matchers.bm25_match import Bm25Matcher
from label_agent.retrieval.matchers.exact_match import ExactMatcher
from label_agent.retrieval.matchers.vector_match import TagServiceVectorMatcher, VectorMatcher
from label_agent.retrieval.tag_service_domain_index import TagServiceDomainIndex
from label_agent.scenarios.registry import ScenarioRegistry
from label_agent.scenarios.s1_career.handler import S1CareerHandler
from label_agent.scenarios.s1_career.pipeline import S1Pipeline
from label_agent.scenarios.s2_skill.handler import S2SkillHandler
from label_agent.scenarios.s2_skill.pipeline import S2Pipeline
from label_agent.scenarios.s3_content.handler import S3ContentHandler
from label_agent.scenarios.s3_content.pipeline import S3Pipeline
from label_agent.scenarios.t1_task_detail.extractors.base import ExtractorRegistry
from label_agent.scenarios.t1_task_detail.extractors.dessert import DessertExtractor
from label_agent.scenarios.t1_task_detail.extractors.relationship import RelationshipExtractor
from label_agent.scenarios.t1_task_detail.extractors.skill import SkillExtractor
from label_agent.scenarios.t1_task_detail.handler import T1TaskDetailHandler
from label_agent.settings import CONFIG_DIR
from label_agent.validation.post_validation import PostValidator
from label_agent.validation.pre_validation import PreValidator
from label_agent.validation.safety.injection_detector import InjectionDetector
from label_agent.validation.safety.pii_detector import PiiDetector
from label_agent.validation.safety.sensitive_word_filter import SensitiveWordFilter

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURES_DIR = CONFIG_DIR / "fixtures"


async def build_domain_index(
    domain: str, embedding_provider: OpenAiEmbeddingProvider
) -> InMemoryDomainVectorIndex:
    """从 fixture YAML 构建领域向量索引。"""
    fixture = FIXTURES_DIR / f"{domain}_dictionary.yaml"
    if not fixture.exists():
        raise FileNotFoundError(f"缺少词表 fixture: {fixture}")
    index = InMemoryDomainVectorIndex.from_yaml(fixture, embedding_provider, domain=domain)
    await index.build()
    return index


def build_evidence_matcher(
    domain: str,
    index: EvidenceDomainIndex,
    llm_gateway: LlmGateway,
    prompt_manager: PromptManager,
    yaml_config: dict[str, Any],
) -> EvidenceCandidateMatcher:
    """装配 S1/S2 的 Top-5 + LLM 强制选择器。"""
    inference_cfg = yaml_config.get("inference") or {}
    prompt_versions = inference_cfg.get("prompt_versions") or {}
    prompt_key = "s1_match" if domain == "career" else "s2_match"
    default_prompt = "s1-match-v2" if domain == "career" else "s2-match-v3"
    policy_cfg = yaml_config.get("policy") or {}
    match_cfg = policy_cfg.get("certificate_match") or {}
    return EvidenceCandidateMatcher(
        domain=domain,
        index=index,
        llm_gateway=llm_gateway,
        prompt_manager=prompt_manager,
        prompt_version=str(prompt_versions.get(prompt_key) or default_prompt),
        audit_threshold=float(match_cfg.get("audit_threshold", 0.85)),
        top_k=int(match_cfg.get("top_k", 5)),
    )


def build_s3_handler(
    llm_gateway: LlmGateway,
    yaml_config: dict[str, Any],
    *,
    prompt_manager: PromptManager | None = None,
    vector_index: InMemoryDomainVectorIndex | None = None,
    tag_service: TagServiceClient | None = None,
) -> S3ContentHandler:
    """装配 S3；默认使用 fixture，生产可注入真实 Tag Service。"""
    prompts = prompt_manager or PromptManager()
    fixture_service = FixtureTagServiceClient.from_yaml(FIXTURES_DIR / "content_dictionary.yaml")
    service = tag_service or fixture_service
    media_guard = MediaGuard(allowed_domains=set(), max_bytes=20 * 1024 * 1024)
    bundle_builder = ContentBundleBuilder(
        media_guard=media_guard,
        text_normalizer=TextNormalizer(),
        ocr_engine=OcrEngine(),
        frame_sampler=VideoFrameSampler(max_duration_sec=120, max_frames=8),
        asr_transcriber=AsrTranscriber(model_size="base", device="cpu"),
        image_vision=ImageVisionExtractor(
            llm_gateway=llm_gateway,
            prompt_manager=prompts,
            media_guard=media_guard,
            vision_prompt_version="s3-vision-v1",
            scene="s3",
        ),
    )
    retriever = CandidateRetriever(
        tag_service=service,
        exact_matcher=ExactMatcher(service),
        alias_matcher=AliasMatcher(service),
        bm25_matcher=Bm25Matcher(service),
        vector_matcher=(
            VectorMatcher(vector_index)
            if vector_index is not None
            else TagServiceVectorMatcher(service) if tag_service is not None else None
        ),
    )
    inference_cfg = yaml_config.get("inference") or {}
    prompt_versions = inference_cfg.get("prompt_versions") or {}
    prompt_version = str(prompt_versions.get("s3") or "s3-v3")
    policy_cfg = yaml_config.get("policy") or {}
    confidence_cfg = policy_cfg.get("confidence") or {}
    policy_version = str(confidence_cfg.get("version") or "provisional-rule-mvp-1")
    scene_cfg = (yaml_config.get("scene") or {}).get("s3") or {}
    auto_create = bool(scene_cfg.get("auto_create_unmatched", False))
    sensitive_filter = SensitiveWordFilter(banned_words=set())
    pii_detector = PiiDetector()
    injection_detector = InjectionDetector()
    pipeline = S3Pipeline(
        content_bundle_builder=bundle_builder,
        candidate_retriever=retriever,
        semantic_proposer=SemanticProposer(llm_gateway, prompts, prompt_version),
        entity_resolver=EntityResolver(),
        pre_validator=PreValidator(
            sensitive_filter,
            pii_detector,
            injection_detector,
            allowed_domains={fixture_service.domain},
        ),
        tag_committer=TagCommitter(
            service,
            auto_create=auto_create,
            confidence_threshold=0.5,
            policy_version=policy_version,
            dictionary_snapshot_version=(
                fixture_service.dictionary_snapshot_version if tag_service is None else ""
            ),
        ),
        post_validator=PostValidator(),
    )
    return S3ContentHandler(pipeline)


def build_t1_handler(
    llm_gateway: LlmGateway,
    yaml_config: dict[str, Any],
    *,
    prompt_manager: PromptManager | None = None,
) -> T1TaskDetailHandler:
    """装配 T1 文本+图片感知、自动三分类和分支字段提取。"""
    prompts = prompt_manager or PromptManager()
    prompt_versions = (yaml_config.get("inference") or {}).get("prompt_versions") or {}
    image_options = (yaml_config.get("perception") or {}).get("certificate_image") or {}
    inference = T1TaskDetailInference(
        llm_gateway,
        prompts,
        classify_prompt_version=str(prompt_versions.get("t1_classify") or "t1-classify-v1"),
        extract_prompt_version=str(prompt_versions.get("t1") or "t1-v1"),
    )
    extractors = ExtractorRegistry()
    extractors.register(RelationshipExtractor(inference))
    extractors.register(SkillExtractor(inference))
    extractors.register(DessertExtractor(inference))
    loader = T1ContentLoader(
        text_normalizer=TextNormalizer(),
        media_guard=MediaGuard(allowed_domains=set(), max_bytes=20 * 1024 * 1024),
        llm_gateway=llm_gateway,
        prompt_manager=prompts,
        vision_prompt_version=str(prompt_versions.get("t1_vision") or "t1-vision-v1"),
        ocr_engine=OcrEngine(),
        image_ocr_options=image_options,
    )
    return T1TaskDetailHandler(extractors, loader, inference)


async def build_mvp_registry(
    *,
    api_key: str | None = None,
    tag_service: TagServiceClient | None = None,
    milvus_proxy: MilvusProxyClient | None = None,
    certificate_media_allowed_domains: set[str] | None = None,
) -> ScenarioRegistry:
    """构建场景注册表；注入 Tag Service 时 S1/S2 使用生产词典。"""
    yaml_config = load_yaml_config()
    key = api_key or require_openai_api_key()
    llm_gateway = build_llm_gateway(key, yaml_config)
    prompt_manager = PromptManager()
    embedding = build_embedding_provider(key)
    career_index: EvidenceDomainIndex
    certificate_index: EvidenceDomainIndex
    if tag_service is None:
        career_index = await build_domain_index("career", embedding)
        certificate_index = await build_domain_index("certificate", embedding)
    else:
        career_index = TagServiceDomainIndex("career", tag_service)
        certificate_index = TagServiceDomainIndex("certificate", tag_service)
    content_index = await build_domain_index("content", embedding) if tag_service is None else None
    perception_cfg = yaml_config.get("perception") or {}
    certificate_image_options = perception_cfg.get("certificate_image") or {}
    configured_certificate_domains = {
        str(domain).strip()
        for domain in perception_cfg.get("certificate_media_allowed_domains") or []
        if str(domain).strip()
    }
    certificate_allowed_domains = (
        certificate_media_allowed_domains
        if certificate_media_allowed_domains is not None
        else configured_certificate_domains
    )
    certificate_ocr = OcrEngine()

    content_loader = CertificateContentLoader(
        text_normalizer=TextNormalizer(),
        media_guard=MediaGuard(
            allowed_domains=certificate_allowed_domains,
            max_bytes=20 * 1024 * 1024,
        ),
        llm_gateway=llm_gateway,
        prompt_manager=prompt_manager,
        vision_prompt_version="s1-vision-v1",
        scene="s1",
        ocr_engine=certificate_ocr,
        image_ocr_options=certificate_image_options,
    )
    proposer = GenerativeProposer(llm_gateway=llm_gateway, prompt_manager=prompt_manager)
    inference_cfg = yaml_config.get("inference") or {}
    prompt_versions = inference_cfg.get("prompt_versions") or {}
    policy_cfg = yaml_config.get("policy") or {}
    match_cfg = policy_cfg.get("certificate_match") or {}
    match_policy_version = str(match_cfg.get("version") or "certificate-match-v2")
    s1_pipeline = S1Pipeline(
        content_loader=content_loader,
        generative_proposer=proposer,
        matcher=build_evidence_matcher(
            "career", career_index, llm_gateway, prompt_manager, yaml_config
        ),
        pii_detector=PiiDetector(),
        injection_detector=InjectionDetector(),
        prompt_version=str(prompt_versions.get("s1") or "s1-v2"),
        policy_version=match_policy_version,
        dictionary_snapshot_version=career_index.dictionary_snapshot_version,
    )
    s2_content_loader = CertificateContentLoader(
        text_normalizer=TextNormalizer(),
        media_guard=MediaGuard(
            allowed_domains=certificate_allowed_domains,
            max_bytes=20 * 1024 * 1024,
        ),
        llm_gateway=llm_gateway,
        prompt_manager=prompt_manager,
        vision_prompt_version="s2-vision-v2",
        scene="s2",
        ocr_engine=certificate_ocr,
        image_ocr_options=certificate_image_options,
    )
    s2_pipeline = S2Pipeline(
        content_loader=s2_content_loader,
        generative_proposer=proposer,
        matcher=build_evidence_matcher(
            "certificate", certificate_index, llm_gateway, prompt_manager, yaml_config
        ),
        pii_detector=PiiDetector(),
        injection_detector=InjectionDetector(),
        prompt_version=str(prompt_versions.get("s2") or "s2-v3"),
        policy_version=match_policy_version,
        dictionary_snapshot_version=certificate_index.dictionary_snapshot_version,
    )
    registry = ScenarioRegistry()
    registry.register(S1CareerHandler(s1_pipeline))
    registry.register(S2SkillHandler(s2_pipeline))
    registry.register(
        build_s3_handler(
            llm_gateway,
            yaml_config,
            prompt_manager=prompt_manager,
            vector_index=content_index,
            tag_service=tag_service,
        )
    )
    registry.register(build_t1_handler(llm_gateway, yaml_config, prompt_manager=prompt_manager))
    registry.register(
        await build_s4_handler(
            llm_gateway,
            embedding,
            yaml_config,
            prompt_manager=prompt_manager,
            milvus_proxy=milvus_proxy,
        )
    )
    return registry
