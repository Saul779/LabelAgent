"""Worker / Ingress 运行时装配。"""

from __future__ import annotations

from dataclasses import dataclass

from label_agent.application.orchestrator import Orchestrator
from label_agent.application.process_task import ProcessTaskUseCase
from label_agent.bootstrap.inference_factory import build_embedding_provider, require_openai_api_key
from label_agent.bootstrap.mvp_scene_factory import build_mvp_registry
from label_agent.core.di import get_container
from label_agent.embedding.tag_vectorizer import TagVectorizer
from label_agent.infrastructure.mq.envelope_parser import EnvelopeParser
from label_agent.infrastructure.mq.factory import create_ingress_consumer, create_publisher
from label_agent.infrastructure.mq.protocols import MqIngressConsumer, MqPublisher
from label_agent.infrastructure.mq.vector_events import KafkaVectorEventConsumer
from label_agent.settings import Settings, get_settings
from label_agent.workers.reconciliation_worker import ReconciliationWorker
from label_agent.workers.vector_worker import VectorWorker


@dataclass
class RuntimeBundle:
    """进程内可复用的运行时依赖。"""

    settings: Settings
    publisher: MqPublisher
    envelope_parser: EnvelopeParser
    process_task: ProcessTaskUseCase | None = None
    orchestrator: Orchestrator | None = None


async def build_runtime(*, with_scenes: bool = False) -> RuntimeBundle:
    """装配 MQ / ProcessTask；with_scenes=True 时额外装配 Orchestrator。"""
    settings = get_settings()
    settings.validate_runtime()
    publisher = create_publisher(settings)
    envelope_parser = EnvelopeParser()

    orchestrator = None
    process_task = None
    if with_scenes:
        container = get_container()
        uses_external_services = settings.app_env.lower() in {"staging", "prod"}
        cfg = worker_config(settings)
        registry = await build_mvp_registry(
            tag_service=container.tag_service if uses_external_services else None,
            milvus_proxy=container.milvus_proxy,
            certificate_media_allowed_domains=settings.certificate_allowed_domain_set,
        )
        orchestrator = Orchestrator(scenario_registry=registry)
        process_task = ProcessTaskUseCase(
            orchestrator,
            publisher,
            max_attempts=int(cfg.get("max_attempts", 5)),
            max_publish_attempts=int(cfg.get("publish_max_attempts", 5)),
            max_receipt_bytes=int(cfg.get("receipt_max_payload_bytes", 900_000)),
        )

    return RuntimeBundle(
        settings=settings,
        publisher=publisher,
        envelope_parser=envelope_parser,
        process_task=process_task,
        orchestrator=orchestrator,
    )


def worker_config(settings: Settings) -> dict:
    """从 yaml 读取 worker 配置。"""
    return dict(settings.yaml_config.get("worker") or {})


def build_job_worker(bundle: RuntimeBundle) -> MqIngressConsumer:
    """构造直接消费 MQ 并执行任务的 Job Worker。"""
    if bundle.process_task is None:
        raise RuntimeError("JobWorker 需要 with_scenes=True 的 RuntimeBundle")
    return create_ingress_consumer(
        bundle.settings,
        envelope_parser=bundle.envelope_parser,
        process_task=bundle.process_task,
    )


def _build_tag_vectorizer(settings: Settings) -> TagVectorizer:
    """装配生产标签向量化器。"""
    container = get_container()
    return TagVectorizer(
        build_embedding_provider(
            require_openai_api_key(settings),
            settings=settings,
        ),
        container.milvus_proxy,
        collection=str(
            ((settings.yaml_config.get("vector") or {}).get("tag_collection")) or "tag_vectors"
        ),
    )


def build_vector_worker(bundle: RuntimeBundle) -> VectorWorker:
    """构造 Kafka 驱动的标签向量化 Worker。"""
    if bundle.settings.effective_mq_backend != "kafka":
        raise RuntimeError("VectorWorker 生产异步模式要求 MQ_BACKEND=kafka")
    container = get_container()
    cfg = worker_config(bundle.settings)
    consumer = KafkaVectorEventConsumer(
        bootstrap_servers=bundle.settings.mq_bootstrap_servers,
        topic=bundle.settings.vector_event_topic,
        consumer_group=bundle.settings.vector_consumer_group,
        poll_timeout_ms=int(cfg.get("vector_poll_timeout_ms", 1000)),
    )
    return VectorWorker(
        container.tag_service,
        _build_tag_vectorizer(bundle.settings),
        consumer,
        poll_interval_sec=float(cfg.get("poll_interval_sec", 1.0)),
    )


def build_reconciliation_worker(bundle: RuntimeBundle) -> ReconciliationWorker:
    """构造标签向量一致性补偿 Worker。"""
    container = get_container()
    cfg = worker_config(bundle.settings)
    return ReconciliationWorker(
        container.tag_service,
        _build_tag_vectorizer(bundle.settings),
        batch_size=int(cfg.get("vector_reconciliation_batch_size", 100)),
        poll_interval_sec=float(cfg.get("reconciliation_poll_interval_sec", 60.0)),
    )
