"""T1 分支提取器协议、注册表与共享字段校验。"""

from __future__ import annotations

from typing import Literal, Protocol

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.t1_result import TaskDetailExtractionError, TaskDetailResult
from label_agent.inference.t1_task_detail import BizTaskType


class TaskDetailExtractor(Protocol):
    """任务详情抽取器协议。"""

    biz_task_type: BizTaskType

    async def extract(self, ctx: JobContext) -> TaskDetailResult: ...


class UnknownTaskTypeError(NonRetryableError):
    """未知任务类型、无法匹配 Extractor 时抛出。"""

    error_code = "UNKNOWN_BIZ_TASK_TYPE"


class InvalidAcceptModeError(NonRetryableError):
    """接单方式缺失或不属于正式枚举。"""

    error_code = "T1_INVALID_ACCEPT_MODE"


class ExtractorRegistry:
    """按 task_type 注册与解析 Extractor。"""

    def __init__(self) -> None:
        """初始化空 Extractor 注册表。"""
        self._extractors: dict[str, TaskDetailExtractor] = {}

    def register(self, extractor: TaskDetailExtractor) -> None:
        """注册某个任务类型的 Extractor。"""
        self._extractors[extractor.biz_task_type] = extractor

    def resolve(self, biz_task_type: BizTaskType) -> TaskDetailExtractor:
        """按任务类型解析 Extractor。"""
        try:
            return self._extractors[biz_task_type]
        except KeyError as exc:
            raise UnknownTaskTypeError(f"未知 biz_task_type: {biz_task_type}") from exc


def require_accept_mode(ctx: JobContext) -> Literal["public", "specified"]:
    """校验并返回正式接单方式枚举。"""
    value = ctx.payload.get("accept_mode")
    if value not in {"public", "specified"}:
        raise InvalidAcceptModeError(f"accept_mode 必须是 public 或 specified，实际为: {value!r}")
    return value


def perception_errors(ctx: JobContext) -> list[TaskDetailExtractionError]:
    """把图片部分失败转为可消费的部分成功错误。"""
    bundle = ctx.content_bundle
    if bundle is None or not any(item.startswith("image") for item in bundle.failed_modalities):
        return []
    return [
        TaskDetailExtractionError(
            code="IMAGE_PERCEPTION_FAILED",
            field="attachments",
            message="至少一张图片未能完成识别，结果主要依据描述与正文",
            retryable=False,
        )
    ]


def extraction_error(code: str, field: str, message: str) -> TaskDetailExtractionError:
    return TaskDetailExtractionError(code=code, field=field, message=message, retryable=False)
