"""重试装饰器：指数退避 + 抖动（§4.5），基于 tenacity 封装统一策略。"""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from label_agent.core.exceptions import RetryableError

T = TypeVar("T")


def with_retry(
    max_attempts: int = 5,
    min_wait_sec: float = 0.5,
    max_wait_sec: float = 30.0,
) -> Callable:
    """异步重试装饰器/包装：对瞬时失败自动重试。"""
    return retry(
        retry=retry_if_exception_type(RetryableError),
        stop=stop_after_attempt(max_attempts),
        wait=wait_random_exponential(min=min_wait_sec, max=max_wait_sec),
        reraise=True,
    )
