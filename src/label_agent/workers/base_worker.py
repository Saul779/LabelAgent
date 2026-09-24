"""BaseWorker：统一启动/停止、优雅关闭、心跳与指数退避重试骨架。"""

from __future__ import annotations

import asyncio
import signal
from abc import ABC, abstractmethod
from contextlib import suppress

from label_agent.core.logging import get_logger

logger = get_logger(__name__)


class BaseWorker(ABC):
    """所有后台 Worker 的基类：提供统一的信号优雅关闭 + 轮询循环 + 异常自愈骨架。"""

    poll_interval_sec: float = 1.0

    def __init__(self) -> None:
        """初始化停止信号，供 run_forever 优雅退出。"""
        self._stopping = asyncio.Event()

    @abstractmethod
    async def poll_once(self) -> bool | None: ...

    async def close(self) -> None:
        """释放 Worker 持有的外部连接；默认无需处理。"""
        return None

    async def run_forever(self) -> None:
        """注册 SIGINT/SIGTERM 优雅停止信号，循环调用 poll_once，单次失败记录日志后按间隔继续。"""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError, AttributeError, RuntimeError):
                loop.add_signal_handler(sig, self._stopping.set)

        try:
            while not self._stopping.is_set():
                try:
                    await self.poll_once()
                except Exception:  # noqa: BLE001 - Worker 主循环必须自愈，异常已在内部分类处理
                    logger.exception("worker_poll_failed")
                await asyncio.sleep(self.poll_interval_sec)
        finally:
            await self.close()
