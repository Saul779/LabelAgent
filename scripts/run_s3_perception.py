#!/usr/bin/env python
"""S3 感知流程本地演示（仅 ContentBundle，不跑召回/打标）。

用法：
  # 纯文本（无需 API Key / OCR）
  poetry run python scripts/run_s3_perception.py configs/fixtures/samples/s3_text_sample.txt

  # 任务图片（Vision，需 OPENAI_API_KEY）
  poetry run python scripts/run_s3_perception.py path/to/poster.png --out var/s3_perception.json

  # 视频（抽帧 OCR + ASR；需 ffmpeg + requirements-perception.txt）
  poetry run python scripts/run_s3_perception.py path/to/demo.mp4

  # 混合 JSON，例如:
  #   {"text":"文案","image_path":"a.png","video_path":"b.mp4"}
  poetry run python scripts/run_s3_perception.py path/to/payload.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS_DIR = Path(__file__).resolve().parent
for _p in (_REPO_ROOT / "src", _SCRIPTS_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from label_agent.core.context import JobContext  # noqa: E402
from label_agent.inference.providers.base import ModelCompletionResult  # noqa: E402
from label_agent.perception.asr.transcriber import AsrTranscriber  # noqa: E402
from label_agent.perception.content_bundle_builder import ContentBundleBuilder  # noqa: E402
from label_agent.perception.extractors.image_vision_extractor import (  # noqa: E402
    ImageVisionExtractor,
)
from label_agent.perception.image.ocr import OcrEngine  # noqa: E402
from label_agent.perception.video.frame_sampler import VideoFrameSampler  # noqa: E402
from mvp_common import (  # noqa: E402
    build_llm_gateway,
    build_media_guard,
    build_prompt_manager,
    build_text_normalizer,
    load_yaml_config,
    read_input_payload,
    require_openai_api_key,
)

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}


class _NoopGateway:
    """无图片任务时的占位网关；若误调 Vision 会给出明确错误。"""

    async def complete(self, request: Any, model_alias: str | None = None) -> ModelCompletionResult:
        _ = request, model_alias
        raise RuntimeError("当前输入不含任务图片，未装配真实 LLM；请设置 OPENAI_API_KEY 后重试图片路径")


def _payload_needs_vision(payload: dict[str, Any]) -> bool:
    """判断 payload 是否包含任务图片（需 Vision）。"""
    for key in ("image_path", "image_uri", "image_url"):
        if isinstance(payload.get(key), str) and str(payload.get(key)).strip():
            return True
    attachments = payload.get("attachments")
    if not isinstance(attachments, list):
        return False
    for item in attachments:
        if isinstance(item, str) and Path(item).suffix.lower() in _IMAGE_SUFFIXES:
            return True
        if isinstance(item, dict):
            declared = str(item.get("type") or item.get("kind") or "").lower()
            if declared in {"image", "img", "photo"}:
                return True
            for key in ("path", "uri", "url", "image_path"):
                value = item.get(key)
                if isinstance(value, str) and Path(value).suffix.lower() in _IMAGE_SUFFIXES:
                    return True
    return False


def _read_s3_payload(path: Path) -> dict[str, Any]:
    """解析 S3 感知输入。"""
    if path.suffix.lower() in _VIDEO_SUFFIXES:
        return {"video_path": str(path)}
    return read_input_payload(path)


async def _run(input_path: Path, out_path: Path | None) -> None:
    """装配 ContentBundleBuilder 并只跑感知阶段。"""
    payload = _read_s3_payload(input_path)
    needs_vision = _payload_needs_vision(payload)

    yaml_config = load_yaml_config()
    prompt_manager = build_prompt_manager()
    media_guard = build_media_guard()

    if needs_vision:
        llm_gateway: Any = build_llm_gateway(require_openai_api_key(), yaml_config)
    else:
        llm_gateway = _NoopGateway()

    builder = ContentBundleBuilder(
        media_guard=media_guard,
        text_normalizer=build_text_normalizer(),
        ocr_engine=OcrEngine(),
        frame_sampler=VideoFrameSampler(max_duration_sec=120, max_frames=8),
        asr_transcriber=AsrTranscriber(model_size="base", device="cpu"),
        image_vision=ImageVisionExtractor(
            llm_gateway=llm_gateway,
            prompt_manager=prompt_manager,
            media_guard=media_guard,
            vision_prompt_version="s3-vision-v1",
            scene="s3",
        ),
    )

    ctx = JobContext(
        job_id=f"job-{uuid.uuid4().hex[:10]}",
        task_id=f"task-{uuid.uuid4().hex[:10]}",
        scene="S3",
        biz_id=str(payload.get("biz_id") or input_path.stem),
        payload=payload,
    )
    print(f"scene=S3 task_id={ctx.task_id} payload_keys={list(payload.keys())}")
    bundle = await builder.build(ctx)
    text = json.dumps(bundle.model_dump(), ensure_ascii=False, indent=2)
    print(text)
    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"已写入: {out_path}")


def main() -> None:
    """S3 感知 CLI 入口。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input_path", type=Path, help="文本/图片/视频/JSON/YAML 输入路径")
    parser.add_argument("--out", type=Path, default=None, help="可选：ContentBundle JSON 落盘路径")
    args = parser.parse_args()
    if not args.input_path.exists():
        raise SystemExit(f"输入不存在: {args.input_path}")
    asyncio.run(_run(args.input_path, args.out))


if __name__ == "__main__":
    main()
