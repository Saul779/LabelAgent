"""T1 场景输出契约 TaskDetailResult。

Agent 只返回任务语义明细；历史接单人、userID、权限与派单结果由业务后端追加。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from label_agent.domain.models.job import JobOutcome


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskDetailExtractionError(_StrictModel):
    """字段级提取错误；调用方不需要解析自然语言文案。"""

    code: str
    field: str | None = None
    message: str
    retryable: bool = False


class TaskDetailResult(_StrictModel):
    """T1 任务详情抽取结果。"""

    schema_version: Literal["1.0"] = "1.0"
    accept_mode: Literal["public", "specified"]
    biz_task_type: Literal["relationship", "skill", "dessert"]
    relation_target: Literal["person", "other_object"] | None = None
    relation_target_detail: str | None = None
    required_skills: list[str] = Field(default_factory=list)
    service_mode: Literal["offline", "non_offline"] | None = None
    extraction_errors: list[TaskDetailExtractionError] = Field(default_factory=list)

    def to_receipt_payload(self) -> dict:
        """序列化为统一 MQ 回执 payload，保留显式 null 字段。"""
        return self.model_dump(mode="json")

    def to_job_outcome(self) -> JobOutcome:
        """按结构化错误决定内部 Job 终态，同时保留可消费的结果 payload。"""
        review_codes = {
            "AMBIGUOUS_RELATION_TARGET",
            "AMBIGUOUS_SERVICE_MODE",
            "MISSING_EXPLICIT_RELATION_TARGET",
            "MISSING_EXPLICIT_REQUIRED_SKILLS",
        }
        if any(error.code in review_codes for error in self.extraction_errors):
            return JobOutcome.NEED_REVIEW
        if self.extraction_errors:
            return JobOutcome.PARTIAL_SUCCESS
        return JobOutcome.SUCCEEDED
