"""ProcessTask：消费一条信封后执行场景并发布回执，不落本地库。"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from label_agent.application.orchestrator import Orchestrator
from label_agent.application.receipt_builder import build_receipt
from label_agent.core.context import JobContext
from label_agent.core.exceptions import NonRetryableError, RetryableError
from label_agent.core.ids import new_job_id
from label_agent.core.logging import get_logger
from label_agent.core.timeutil import now_ms
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.domain.models.job import JobOutcome
from label_agent.domain.models.receipt import Receipt
from label_agent.infrastructure.mq.protocols import MqPublisher

logger = get_logger(__name__)


class MissingSceneError(NonRetryableError):
    """信封缺少 scene，无法路由。"""

    error_code = "MISSING_SCENE"


@dataclass(frozen=True)
class ProcessTaskResult:
    """单次任务处理结果。"""

    job_id: str
    outcome: JobOutcome
    published: bool


class ProcessTaskUseCase:
    """解析场景后执行 Orchestrator，并把回执发到 callback_topic。"""

    def __init__(
        self,
        orchestrator: Orchestrator,
        publisher: MqPublisher,
        *,
        max_attempts: int = 5,
        max_publish_attempts: int = 5,
        max_receipt_bytes: int = 900_000,
    ) -> None:
        """注入编排器、发布器与重试/体积上限。"""
        self._orchestrator = orchestrator
        self._publisher = publisher
        self._max_attempts = max_attempts
        self._max_publish_attempts = max_publish_attempts
        self._max_receipt_bytes = max_receipt_bytes

    async def execute(self, envelope: ParsedEnvelope) -> ProcessTaskResult:
        """执行一条任务；可重试错误在进程内退避，超限后发失败回执。"""
        scene = envelope.v2.scene
        if not scene:
            raise MissingSceneError("payload.scene 缺失，无法路由到 ScenarioHandler")

        ctx = context_from_envelope(envelope)
        last_error: RetryableError | None = None
        started = now_ms()
        for attempt in range(1, self._max_attempts + 1):
            try:
                outcome, receipt = await self._orchestrator.process(
                    envelope,
                    ctx,
                    started_at_ms=started,
                )
                published, oversized = await self._publish(envelope, receipt, ctx.job_id)
                if oversized:
                    outcome = JobOutcome.FAILED
                logger.info(
                    "job_finished",
                    extra={
                        "extra_fields": {
                            "job_id": ctx.job_id,
                            "outcome": outcome.value,
                            "attempt": attempt,
                            "published": published,
                        }
                    },
                )
                return ProcessTaskResult(
                    job_id=ctx.job_id,
                    outcome=outcome,
                    published=published,
                )
            except RetryableError as exc:
                last_error = exc
                if attempt >= self._max_attempts:
                    break
                delay_sec = min(2 ** max(attempt - 1, 0), 60)
                logger.info(
                    "job_retry_wait",
                    extra={
                        "extra_fields": {
                            "job_id": ctx.job_id,
                            "attempt": attempt,
                            "delay_sec": delay_sec,
                        }
                    },
                )
                await asyncio.sleep(delay_sec)

        receipt = build_receipt(
            envelope=envelope,
            outcome=JobOutcome.FAILED,
            job_id=ctx.job_id,
            started_at_ms=started,
            result_payload={
                "retryable": False,
                "error_code": "MAX_ATTEMPTS_EXCEEDED",
                "error": str(last_error) if last_error else "max attempts exceeded",
            },
        )
        published, _ = await self._publish(envelope, receipt, ctx.job_id)
        logger.info(
            "job_failed_max_attempts",
            extra={
                "extra_fields": {
                    "job_id": ctx.job_id,
                    "attempt": self._max_attempts,
                    "published": published,
                }
            },
        )
        return ProcessTaskResult(
            job_id=ctx.job_id,
            outcome=JobOutcome.FAILED,
            published=published,
        )

    async def _publish(
        self,
        envelope: ParsedEnvelope,
        receipt: Receipt,
        job_id: str,
    ) -> tuple[bool, bool]:
        """发布回执；超限改为失败回执，发布失败在进程内有限重试。

        返回 (published, oversized)。
        """
        to_send, oversized = self._enforce_receipt_size(envelope, receipt, job_id)
        last_exc: Exception | None = None
        for attempt in range(1, self._max_publish_attempts + 1):
            try:
                await self._publisher.publish(envelope.v1.callback_topic, to_send)
                return True, oversized
            except ValueError as exc:
                raise NonRetryableError(str(exc)) from exc
            except Exception as exc:  # noqa: BLE001 - MQ 适配器异常统一进入有限重试
                last_exc = exc
                if attempt >= self._max_publish_attempts:
                    break
                await asyncio.sleep(min(2 ** max(attempt - 1, 0), 60))
        raise RetryableError(f"回执发布失败: {type(last_exc).__name__}: {last_exc}") from last_exc

    def _enforce_receipt_size(
        self,
        envelope: ParsedEnvelope,
        receipt: Receipt,
        job_id: str,
    ) -> tuple[Receipt, bool]:
        """超过 Kafka 安全阈值时改发精简失败回执，避免无限重试超大消息。"""
        payload_size = len(receipt.model_dump_json().encode("utf-8"))
        if payload_size <= self._max_receipt_bytes:
            return receipt, False
        logger.error(
            "receipt_too_large",
            extra={
                "extra_fields": {
                    "job_id": job_id,
                    "task_id": receipt.task_id,
                    "payload_size": payload_size,
                    "max_receipt_bytes": self._max_receipt_bytes,
                }
            },
        )
        return (
            build_receipt(
                envelope=envelope,
                outcome=JobOutcome.FAILED,
                job_id=job_id,
                started_at_ms=now_ms(),
                result_payload={
                    "retryable": False,
                    "error_code": "PAYLOAD_TOO_LARGE",
                    "error": f"PAYLOAD_TOO_LARGE: {payload_size} > {self._max_receipt_bytes}",
                },
            ),
            True,
        )


def context_from_envelope(envelope: ParsedEnvelope) -> JobContext:
    """从信封构造单次执行的 JobContext。"""
    return JobContext(
        job_id=new_job_id(),
        task_id=envelope.v1.task_id,
        scene=envelope.v2.scene or "",
        biz_id=envelope.v2.biz_id or "",
        payload=dict(envelope.v1.payload),
        data_version=envelope.v2.data_version,
        version_protected=envelope.version_protected,
        trace_id=envelope.v2.trace_id,
    )
