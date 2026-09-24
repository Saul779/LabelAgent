#!/usr/bin/env python
"""运维脚本：重放指定 Job（不得用新 task_id 绕过幂等键，建立 replay_generation，§4.5）。

用法：poetry run python scripts/replay_job.py --job-id job-xxx --operator alice
"""
from __future__ import annotations

import argparse
import asyncio


async def _replay(job_id: str, operator: str) -> None:
    raise NotImplementedError("装配 TriggerReplayUseCase 依赖后调用 execute()")


def main() -> None:
    """按 job_id 触发重放的 CLI 入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--operator", required=True)
    args = parser.parse_args()
    asyncio.run(_replay(args.job_id, args.operator))


if __name__ == "__main__":
    main()
