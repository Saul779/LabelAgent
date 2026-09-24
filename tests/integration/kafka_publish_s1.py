"""向真实 Kafka ingress Topic 投递一条 S1 任务信封。

用法（仓库根目录）：
  poetry run python tests/integration/kafka_publish_s1.py
  poetry run python tests/integration/kafka_publish_s1.py --text "曾任 Python 工程师"
  poetry run python tests/integration/kafka_publish_s1.py --envelope path/to/envelope.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# 保证以脚本方式运行时可导入同目录 helpers
_TESTS_INTEGRATION = Path(__file__).resolve().parent
if str(_TESTS_INTEGRATION) not in sys.path:
    sys.path.insert(0, str(_TESTS_INTEGRATION))

from kafka_helpers import (  # noqa: E402
    build_s1_envelope,
    ingress_topic,
    kafka_bootstrap_servers,
    load_envelope_json,
    load_project_dotenv,
    publish_ingress,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="投递 S1 任务到 Kafka ingress Topic")
    parser.add_argument(
        "--bootstrap",
        default=None,
        help="Kafka bootstrap，默认读 REAL_KAFKA_BOOTSTRAP_SERVERS / MQ_BOOTSTRAP_SERVERS",
    )
    parser.add_argument("--topic", default=None, help="ingress Topic，默认 MQ_INGRESS_TOPIC")
    parser.add_argument(
        "--text",
        default=None,
        help="证书/简历文本；指定 --envelope 时也可覆盖 text",
    )
    parser.add_argument(
        "--envelope",
        type=Path,
        default=None,
        help="自定义信封 JSON（对象或数组首条）",
    )
    parser.add_argument("--task-id", default=None, help="覆盖 task_id")
    parser.add_argument("--callback-topic", default=None, help="覆盖 callback_topic")
    return parser.parse_args()


async def _main() -> int:
    load_project_dotenv()
    args = _parse_args()
    if args.envelope is not None:
        envelope = load_envelope_json(args.envelope)
        if args.task_id:
            envelope["task_id"] = args.task_id
        if args.callback_topic:
            envelope["callback_topic"] = args.callback_topic
        if args.text is not None:
            payload = dict(envelope.get("payload") or {})
            payload["text"] = args.text
            payload.setdefault("scene", "S1")
            envelope["payload"] = payload
    else:
        envelope = build_s1_envelope(
            text=args.text,
            task_id=args.task_id,
            callback=args.callback_topic,
        )

    task_id = await publish_ingress(
        envelope,
        bootstrap_servers=args.bootstrap,
        topic=args.topic,
    )
    print(
        json.dumps(
            {
                "ok": True,
                "bootstrap": args.bootstrap or kafka_bootstrap_servers(),
                "topic": args.topic or ingress_topic(),
                "task_id": task_id,
                "callback_topic": envelope.get("callback_topic"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
