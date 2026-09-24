"""Orchestrator：单个 Job 的端到端驱动（路由 -> 执行 ScenarioHandler -> 组装回执）。"""

from __future__ import annotations

from label_agent.application.receipt_builder import build_receipt
from label_agent.core.context import JobContext
from label_agent.core.exceptions import (
    NeedReviewError,
    NonRetryableError,
    RetryableError,
    SupersededError,
)
from label_agent.core.timeutil import now_ms
from label_agent.domain.models.envelope import ParsedEnvelope
from label_agent.domain.models.job import JobOutcome
from label_agent.domain.models.receipt import Receipt
from label_agent.scenarios.registry import ScenarioRegistry


class Orchestrator:
    """Job 编排器：驱动场景 Handler，并把异常映射为 Job 终态与回执。"""

    def __init__(self, scenario_registry: ScenarioRegistry) -> None:
        """注入场景路由。"""
        self._scenario_registry = scenario_registry

    async def process(
        self,
        envelope: ParsedEnvelope,
        ctx: JobContext,
        *,
        started_at_ms: int | None = None,
    ) -> tuple[JobOutcome, Receipt]:
        """处理单个 Job：路由场景、执行并组装回执。"""
        started = started_at_ms if started_at_ms is not None else now_ms()
        handler = self._scenario_registry.resolve(envelope)
        outcome: JobOutcome
        result_payload: dict | None = None
        error_code: str | None = None
        last_error: str | None = None

        try:
            result = await handler.run(ctx)
            result_payload = result.to_receipt_payload()
            outcome_resolver = getattr(result, "to_job_outcome", None)
            outcome = outcome_resolver() if callable(outcome_resolver) else JobOutcome.SUCCEEDED
        except SupersededError as exc:
            outcome = JobOutcome.SUPERSEDED
            error_code = getattr(exc, "error_code", "SUPERSEDED")
            last_error = str(exc)
        except NeedReviewError as exc:
            outcome = JobOutcome.NEED_REVIEW
            error_code = getattr(exc, "error_code", "NEED_REVIEW")
            last_error = str(exc)
        except RetryableError:
            raise
        except NonRetryableError as exc:
            outcome = JobOutcome.FAILED
            error_code = getattr(exc, "error_code", "NON_RETRYABLE_ERROR")
            last_error = str(exc)
        except Exception as exc:  # noqa: BLE001 - 未分类异常按不可重试失败收口
            outcome = JobOutcome.FAILED
            error_code = "UNHANDLED_ERROR"
            last_error = str(exc)

        if result_payload is None:
            result_payload = {}
        if error_code:
            result_payload.setdefault("error_code", error_code)
        if last_error:
            result_payload.setdefault("error", last_error)

        receipt = build_receipt(
            envelope=envelope,
            outcome=outcome,
            job_id=ctx.job_id,
            started_at_ms=started,
            result_payload=result_payload,
        )
        return outcome, receipt
