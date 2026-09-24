"""MockIngressConsumer：用 fixture/固定信封模拟 MQ 入站，并直接执行任务。"""

from __future__ import annotations

import asyncio
import contextlib
import json
import signal
from pathlib import Path
from typing import Any

from label_agent.application.process_task import ProcessTaskUseCase
from label_agent.core.logging import get_logger
from label_agent.infrastructure.mq.envelope_parser import EnvelopeParser
from label_agent.workers.base_worker import BaseWorker

logger = get_logger(__name__)


class MockIngressConsumer(BaseWorker):
    """从本地 fixture 加载固定任务信封，逐条调用 ProcessTaskUseCase。"""

    def __init__(
        self,
        envelope_parser: EnvelopeParser,
        process_task: ProcessTaskUseCase,
        fixture_path: str | Path,
        *,
        replay: str = "once",
        poll_interval_sec: float = 1.0,
    ) -> None:
        """注入解析器、处理用例、fixture 路径与 replay 策略（once|loop）。"""
        super().__init__()
        self.poll_interval_sec = poll_interval_sec
        self._parser = envelope_parser
        self._process_task = process_task
        self._fixture_path = Path(fixture_path)
        self._replay = replay
        self._queue: list[dict[str, Any]] = []
        self._loaded = False

    def _load_fixture(self) -> None:
        """加载 fixture；loop 模式下允许在耗尽后重新装载。"""
        if not self._fixture_path.exists():
            raise FileNotFoundError(f"MQ mock fixture 不存在: {self._fixture_path}")
        raw = json.loads(self._fixture_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            messages = [raw]
        elif isinstance(raw, list):
            messages = raw
        else:
            raise ValueError("MQ mock fixture 必须是对象或对象数组")
        self._queue = list(messages)
        self._loaded = True
        logger.info(
            "mock_ingress_loaded",
            extra={"extra_fields": {"count": len(self._queue), "path": str(self._fixture_path)}},
        )

    async def poll_once(self) -> bool:
        """处理队列中下一条信封；once 模式下队列空则设置停止标志。"""
        if not self._loaded or (not self._queue and self._replay == "loop"):
            self._load_fixture()
        if not self._queue:
            if self._replay == "once":
                logger.info("mock_ingress_drained")
                self._stopping.set()
            return False

        raw = self._queue.pop(0)
        envelope = self._parser.parse(raw)
        result = await self._process_task.execute(envelope)
        logger.info(
            "mock_ingress_acked",
            extra={
                "extra_fields": {
                    "job_id": result.job_id,
                    "outcome": result.outcome.value,
                    "published": result.published,
                    "task_id": envelope.v1.task_id,
                }
            },
        )
        return True

    async def run_forever(self) -> None:
        """注册停止信号并轮询；fixture 耗尽（once）后退出。"""
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            if hasattr(loop, "add_signal_handler"):
                with contextlib.suppress(NotImplementedError):
                    loop.add_signal_handler(sig, self._stopping.set)

        while not self._stopping.is_set():
            try:
                await self.poll_once()
            except Exception:  # noqa: BLE001
                logger.exception("mock_ingress_poll_failed")
            if self._stopping.is_set():
                break
            await asyncio.sleep(self.poll_interval_sec)
