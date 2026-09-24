#!/usr/bin/env python
"""S3 动态内容分类与标签 MVP 本地演示入口。

用法：
  poetry run python scripts/run_s3_mvp.py configs/fixtures/samples/s3_text_sample.txt
  poetry run python scripts/run_s3_mvp.py path/to/payload.json --out var/s3_result.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
for _path in (_REPO_ROOT / "src", _SCRIPTS_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from mvp_common import (  # noqa: E402
    build_domain_index,
    build_embedding_provider,
    build_llm_gateway,
    load_yaml_config,
    read_input_payload,
    require_openai_api_key,
)

from label_agent.bootstrap.mvp_scene_factory import build_s3_handler  # noqa: E402
from label_agent.core.context import JobContext  # noqa: E402


async def _run(input_path: Path, out_path: Path | None) -> None:
    """装配 S3 依赖，读取本地输入并执行一次完整内容打标管线。"""
    yaml_config = load_yaml_config()
    api_key = require_openai_api_key()
    llm_gateway = build_llm_gateway(api_key, yaml_config)
    vector_index = await build_domain_index("content", build_embedding_provider(api_key))
    handler = build_s3_handler(llm_gateway, yaml_config, vector_index=vector_index)
    payload = read_input_payload(input_path)
    ctx = JobContext(
        job_id=f"job-{uuid.uuid4().hex[:10]}",
        task_id=f"task-{uuid.uuid4().hex[:10]}",
        scene="S3",
        biz_id=str(payload.get("biz_id") or input_path.stem),
        payload=payload,
        data_version=payload.get("data_version"),
    )
    result = await handler.run(ctx)
    output_text = json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2)
    print(output_text)
    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output_text, encoding="utf-8")
        print(f"已写入: {out_path}")


def main() -> None:
    """解析命令行参数并启动 S3 MVP 异步执行入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", type=Path, help="文本/图片/视频/JSON/YAML 输入路径")
    parser.add_argument("--out", type=Path, default=None, help="可选：结果 JSON 落盘路径")
    args = parser.parse_args()
    if not args.input_path.exists():
        raise SystemExit(f"输入不存在: {args.input_path}")
    asyncio.run(_run(args.input_path, args.out))


if __name__ == "__main__":
    main()
