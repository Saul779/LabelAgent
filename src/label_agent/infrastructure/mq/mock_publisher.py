"""MockPublisher：预留 MqPublisher 接口，MVP 用日志 + 本地文件代替真实 MQ 出站。"""

from __future__ import annotations

from pathlib import Path

import orjson

from label_agent.core.logging import get_logger
from label_agent.domain.models.receipt import Receipt

logger = get_logger(__name__)


class MockPublisher:
    """本地回执发布：白名单校验后写日志，并可选落盘供联调查看。"""

    def __init__(
        self,
        callback_topic_whitelist: set[str],
        receipt_dir: str | Path | None = "var/receipts",
    ) -> None:
        """注入白名单与本地回执目录（None 表示仅打日志）。"""
        self._whitelist = callback_topic_whitelist
        self._receipt_dir = Path(receipt_dir) if receipt_dir else None
        self.published: list[Receipt] = []

    async def publish(self, callback_topic: str, receipt: Receipt) -> None:
        """校验白名单后记录回执；目录存在时写入 JSON 文件。"""
        if callback_topic not in self._whitelist:
            raise ValueError(f"callback_topic 不在白名单: {callback_topic}")

        self.published.append(receipt)
        payload = receipt.model_dump()
        logger.info(
            "mock_mq_publish",
            extra={"extra_fields": {"callback_topic": callback_topic, "task_id": receipt.task_id}},
        )

        if self._receipt_dir is None:
            return
        self._receipt_dir.mkdir(parents=True, exist_ok=True)
        filename = f"{receipt.task_id}_{receipt.timestamp}.json"
        path = self._receipt_dir / filename
        path.write_bytes(orjson.dumps(payload, option=orjson.OPT_INDENT_2))
