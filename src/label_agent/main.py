"""进程入口：按 --mode 分发 API 与各后台 Worker。

生产部署中每种 mode 对应独立的 K8s Deployment（见 deploy/k8s）。
MVP：mq.backend=mock 时用 fixture 入站 + MockPublisher 出站。

"""

from __future__ import annotations

import argparse
import asyncio
import logging.config

import yaml  # type: ignore[import-untyped]

from label_agent.core.tracing import setup_tracing
from label_agent.settings import CONFIG_DIR, get_settings

_MODES = (
    "api",
    "job_worker",
    "vector_worker",
    "reconciliation_worker",
)


def _setup_logging() -> None:
    """根据配置初始化日志格式与级别。"""
    logging_config_path = CONFIG_DIR / "logging.yaml"
    if logging_config_path.exists():
        logging.config.dictConfig(yaml.safe_load(logging_config_path.read_text(encoding="utf-8")))
    else:
        logging.basicConfig(level=logging.INFO)


def _run_api() -> None:
    """启动 API 服务进程。"""
    import uvicorn

    from label_agent.api.app import create_app

    get_settings().validate_runtime()
    uvicorn.run(create_app(), host="0.0.0.0", port=8000)


async def _run_worker_async(mode: str) -> None:
    """异步启动指定类型的后台 Worker。"""
    from label_agent.workers.factory import (
        build_job_worker,
        build_reconciliation_worker,
        build_runtime,
        build_vector_worker,
    )

    if mode == "job_worker":
        bundle = await build_runtime(with_scenes=True)
        job_worker = build_job_worker(bundle)
        await job_worker.run_forever()
        return

    if mode == "vector_worker":
        bundle = await build_runtime(with_scenes=False)
        vector_worker = build_vector_worker(bundle)
        await vector_worker.run_forever()
        return

    if mode == "reconciliation_worker":
        bundle = await build_runtime(with_scenes=False)
        reconciliation_worker = build_reconciliation_worker(bundle)
        await reconciliation_worker.run_forever()
        return

    raise ValueError(f"未知 mode: {mode}")


def main() -> None:
    """CLI 入口：解析子命令并启动 API 或 Worker。"""
    parser = argparse.ArgumentParser(prog="label-agent")
    parser.add_argument("--mode", choices=_MODES, default="api")
    args = parser.parse_args()

    _setup_logging()
    settings = get_settings()
    setup_tracing(settings.otel_exporter_otlp_endpoint)

    if args.mode == "api":
        _run_api()
    else:
        asyncio.run(_run_worker_async(args.mode))


if __name__ == "__main__":
    main()
