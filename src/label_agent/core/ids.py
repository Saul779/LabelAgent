"""ID 生成：job_id/model_run_id/event_id 兜底生成等。"""

from __future__ import annotations

import uuid


def new_job_id() -> str:
    """生成新的 Job ID，用于单次执行追踪与回执关联。"""
    return f"job-{uuid.uuid4()}"


def new_model_run_id() -> str:
    """生成模型运行 ID，关联一次 LLM/推理调用。"""
    return f"run-{uuid.uuid4()}"


def fallback_event_id(task_id: str) -> str:
    """v1 协议无 event_id 时的降级兜底（§4.1 D006）。调用方需同时记录 degraded_idempotency=true。"""
    return f"fallback-{task_id}"
