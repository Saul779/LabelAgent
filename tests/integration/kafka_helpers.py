"""真实 Kafka 联调辅助：构造信封、投递 ingress、消费 callback 回执。

供手动脚本与联调用例复用；默认读取环境变量（可与仓库根目录 .env 对齐）。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from dotenv import load_dotenv

_DEFAULT_S1_TEXT = (
    "持有软件工程师职业资格证书。\n"
    "工作内容包括使用 Python 进行后端开发，熟悉 MySQL 数据库设计与 Redis 缓存，\n"
    "参与 Docker 容器化部署，具备接口联调与单元测试经验。\n"
    "曾担任 Python 开发工程师，负责业务系统维护与性能优化。\n"
)


def load_project_dotenv() -> None:
    """从仓库根目录加载 .env（若存在）。"""
    repo_root = Path(__file__).resolve().parents[2]
    load_dotenv(repo_root / ".env", override=False)


def kafka_bootstrap_servers() -> str:
    """Kafka bootstrap，优先 REAL_KAFKA_BOOTSTRAP_SERVERS，其次 MQ_BOOTSTRAP_SERVERS。"""
    return (
        os.getenv("REAL_KAFKA_BOOTSTRAP_SERVERS")
        or os.getenv("MQ_BOOTSTRAP_SERVERS")
        or "localhost:9092"
    )


def ingress_topic() -> str:
    """入站 Topic。"""
    return os.getenv("MQ_INGRESS_TOPIC") or "agent.task.ingress"


def callback_topic() -> str:
    """回执 Topic：取白名单首项，或默认 agent.task.callback。"""
    whitelist = os.getenv("MQ_CALLBACK_TOPIC_WHITELIST") or "agent.task.callback"
    first = whitelist.split(",")[0].strip()
    return first or "agent.task.callback"


def build_s1_envelope(
    *,
    text: str | None = None,
    task_id: str | None = None,
    event_id: str | None = None,
    biz_id: str | None = None,
    callback: str | None = None,
    priority: int = 2,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """构造与线上协议一致的 S1 入站信封。"""
    suffix = uuid4().hex[:12]
    return {
        "task_id": task_id or f"task-s1-{suffix}",
        "task_type": "mark_tag",
        "payload_type": "certificate",
        "payload": {
            "scene": "S1",
            "biz_id": biz_id or f"career-{suffix}",
            "event_id": event_id or f"evt-s1-{suffix}",
            "text": text if text is not None else _DEFAULT_S1_TEXT,
        },
        "priority": priority,
        "timestamp": timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
        "callback_topic": callback or callback_topic(),
    }


def load_envelope_json(path: Path) -> dict[str, Any]:
    """从 JSON 文件加载单条信封（对象或仅取数组首条）。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, list):
        if not raw:
            raise ValueError(f"信封文件为空数组: {path}")
        raw = raw[0]
    if not isinstance(raw, dict):
        raise ValueError(f"信封必须是 JSON 对象: {path}")
    return raw


async def publish_ingress(
    envelope: dict[str, Any],
    *,
    bootstrap_servers: str | None = None,
    topic: str | None = None,
) -> str:
    """向 ingress Topic 投递一条 JSON 信封，返回 task_id。"""
    servers = bootstrap_servers or kafka_bootstrap_servers()
    target = topic or ingress_topic()
    producer = AIOKafkaProducer(bootstrap_servers=servers)
    await producer.start()
    try:
        payload = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
        await producer.send_and_wait(target, payload)
    finally:
        await producer.stop()
    return str(envelope.get("task_id") or "")


async def watch_receipts(
    *,
    bootstrap_servers: str | None = None,
    topic: str | None = None,
    group_id: str | None = None,
    task_id: str | None = None,
    timeout_sec: float = 120.0,
    max_messages: int = 1,
    from_beginning: bool = False,
) -> list[dict[str, Any]]:
    """消费 callback Topic 回执；可按 task_id 过滤。

    Returns:
        解析后的回执 dict 列表。
    """
    servers = bootstrap_servers or kafka_bootstrap_servers()
    target = topic or callback_topic()
    group = group_id or f"label-agent-receipt-watch-{uuid4().hex[:8]}"
    consumer = AIOKafkaConsumer(
        target,
        bootstrap_servers=servers,
        group_id=group,
        auto_offset_reset="earliest" if from_beginning else "latest",
        enable_auto_commit=True,
    )
    await consumer.start()
    receipts: list[dict[str, Any]] = []
    try:
        deadline = time.monotonic() + timeout_sec
        while len(receipts) < max_messages:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            batch = await consumer.getmany(
                timeout_ms=min(1000, int(remaining * 1000)),
                max_records=10,
            )
            for records in batch.values():
                for record in records:
                    try:
                        body = json.loads(record.value.decode("utf-8"))
                    except (UnicodeError, json.JSONDecodeError):
                        continue
                    if task_id and str(body.get("task_id") or "") != task_id:
                        continue
                    receipts.append(body)
                    if len(receipts) >= max_messages:
                        return receipts
    finally:
        await consumer.stop()
    return receipts
