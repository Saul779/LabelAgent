"""从真实 Kafka callback Topic 读取回执。

用法（仓库根目录，需先启动 job_worker）：
  poetry run python tests/integration/kafka_watch_receipt.py
  poetry run python tests/integration/kafka_watch_receipt.py --task-id task-s1-xxx
  poetry run python tests/integration/kafka_watch_receipt.py --from-beginning --max 5
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

_TESTS_INTEGRATION = Path(__file__).resolve().parent
if str(_TESTS_INTEGRATION) not in sys.path:
    sys.path.insert(0, str(_TESTS_INTEGRATION))

from kafka_helpers import (  # noqa: E402
    callback_topic,
    kafka_bootstrap_servers,
    load_project_dotenv,
    watch_receipts,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="消费 Kafka callback Topic 回执")
    parser.add_argument(
        "--bootstrap",
        default=None,
        help="Kafka bootstrap，默认读 REAL_KAFKA_BOOTSTRAP_SERVERS / MQ_BOOTSTRAP_SERVERS",
    )
    parser.add_argument("--topic", default=None, help="callback Topic，默认白名单首项")
    parser.add_argument("--group-id", default=None, help="消费组；默认每次随机，避免抢占线上组")
    parser.add_argument("--task-id", default=None, help="只打印匹配的 task_id")
    parser.add_argument("--timeout", type=float, default=120.0, help="等待超时秒数")
    parser.add_argument("--max", type=int, default=1, dest="max_messages", help="最多收取条数")
    parser.add_argument(
        "--from-beginning",
        action="store_true",
        help="从 earliest 读（新 group）；默认 latest 只看新回执",
    )
    return parser.parse_args()


async def _main() -> int:
    load_project_dotenv()
    args = _parse_args()
    print(
        json.dumps(
            {
                "waiting": True,
                "bootstrap": args.bootstrap or kafka_bootstrap_servers(),
                "topic": args.topic or callback_topic(),
                "task_id_filter": args.task_id,
                "timeout_sec": args.timeout,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    receipts = await watch_receipts(
        bootstrap_servers=args.bootstrap,
        topic=args.topic,
        group_id=args.group_id,
        task_id=args.task_id,
        timeout_sec=args.timeout,
        max_messages=args.max_messages,
        from_beginning=args.from_beginning,
    )
    if not receipts:
        print(json.dumps({"ok": False, "error": "timeout_or_empty"}, ensure_ascii=False))
        return 1
    print(
        json.dumps(
            {"ok": True, "count": len(receipts), "receipts": receipts},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
