#!/usr/bin/env python
"""S4 商品打标 MVP 本地测试入口。

用法：
  poetry run python scripts/run_s4_mvp.py --title "新鲜红富士苹果 5斤装"
  poetry run python scripts/run_s4_mvp.py --title "无线蓝牙耳机" --image path/to/1.jpg
  poetry run python scripts/run_s4_mvp.py payload.json --out var/s4_result.json
  poetry run python scripts/run_s4_mvp.py payload.yaml --allow-domain img.example.com

JSON/YAML payload 示例：
  {"product_id":"p-1","title":"新鲜苹果","images":["path/to/apple.jpg"]}
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT / "src"))

from label_agent.bootstrap.inference_factory import (  # noqa: E402
    build_embedding_provider,
    build_llm_gateway,
    load_yaml_config,
    require_openai_api_key,
)
from label_agent.bootstrap.s4_scene_factory import build_s4_handler  # noqa: E402
from label_agent.core.context import JobContext  # noqa: E402

_PAYLOAD_SUFFIXES = {".json", ".yaml", ".yml"}
_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".heic", ".avif"}


def _read_input(path: Path | None) -> dict[str, Any]:
    """读取可选 JSON/YAML、标题文本或单张商品图片。"""
    if path is None:
        return {}
    if not path.exists():
        raise SystemExit(f"输入不存在: {path}")
    suffix = path.suffix.lower()
    if suffix in _PAYLOAD_SUFFIXES:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise SystemExit("S4 JSON/YAML 输入必须是对象")
        if data.get("payload_type") == "product" and isinstance(data.get("payload"), dict):
            data = dict(data["payload"])
        return _normalize_payload_refs(data, base_dir=path.parent)
    if suffix in _IMAGE_SUFFIXES:
        return {"images": [str(path.resolve())]}
    title = path.read_text(encoding="utf-8").strip()
    return {"title": title} if title else {}


def _normalize_payload_refs(payload: dict[str, Any], *, base_dir: Path) -> dict[str, Any]:
    """将 payload 中的相对本地图片路径按配置文件目录解析。"""
    normalized = dict(payload)
    images = normalized.get("images")
    if isinstance(images, str):
        normalized["images"] = [_normalize_image_ref(images, base_dir=base_dir)]
    elif isinstance(images, list):
        normalized["images"] = [
            _normalize_image_item(item, base_dir=base_dir) for item in images
        ]
    return normalized


def _normalize_image_item(item: Any, *, base_dir: Path) -> Any:
    if isinstance(item, str):
        return _normalize_image_ref(item, base_dir=base_dir)
    if not isinstance(item, dict):
        return item
    normalized = dict(item)
    for key in ("url", "uri", "path", "image_url", "image_uri", "image_path"):
        if isinstance(normalized.get(key), str) and normalized[key].strip():
            normalized[key] = _normalize_image_ref(normalized[key], base_dir=base_dir)
            break
    return normalized


def _normalize_image_ref(ref: str, *, base_dir: Path) -> str:
    value = ref.strip()
    if value.startswith(("http://", "https://", "data:")):
        return value
    path = Path(value)
    if not path.is_absolute():
        path = base_dir / path
    if not path.exists() or not path.is_file():
        raise SystemExit(f"商品图片不存在: {path}")
    return str(path.resolve())


def _merge_cli_payload(
    payload: dict[str, Any],
    *,
    title: str | None,
    images: list[str],
    product_id: str | None,
) -> dict[str, Any]:
    merged = dict(payload)
    if title is not None:
        merged["title"] = title.strip()
    existing_images = merged.get("images")
    if isinstance(existing_images, str):
        combined: list[Any] = [existing_images]
    elif isinstance(existing_images, list):
        combined = list(existing_images)
    else:
        combined = []
    combined.extend(
        _normalize_image_ref(ref, base_dir=Path.cwd()) for ref in images if ref.strip()
    )
    if combined:
        merged["images"] = combined
    if product_id:
        merged["product_id"] = product_id
    if not str(merged.get("title") or "").strip() and not merged.get("images"):
        raise SystemExit("必须通过 --title、--image 或输入文件提供标题/图片")
    return merged


def _apply_allowed_domains(config: dict[str, Any], domains: list[str]) -> None:
    """仅为本次测试追加远程图片白名单，不修改配置文件。"""
    if not domains:
        return
    scene = config.setdefault("scene", {})
    s4 = scene.setdefault("s4", {})
    configured = list(s4.get("media_allowed_domains") or [])
    for domain in domains:
        hostname = urlparse(f"//{domain.strip()}").hostname
        if not hostname:
            raise SystemExit(f"无效白名单域名: {domain}")
        if hostname not in configured:
            configured.append(hostname)
    s4["media_allowed_domains"] = configured


async def _run(args: argparse.Namespace) -> None:
    payload = _merge_cli_payload(
        _read_input(args.input_path),
        title=args.title,
        images=args.images,
        product_id=args.product_id,
    )
    config = load_yaml_config(args.env)
    _apply_allowed_domains(config, args.allow_domains)
    api_key = require_openai_api_key()

    print("正在构建 S4 类目向量索引（首次执行可能需要较长时间）...", file=sys.stderr)
    handler = await build_s4_handler(
        build_llm_gateway(api_key, config),
        build_embedding_provider(api_key),
        config,
    )
    product_id = str(payload.get("product_id") or f"product-{uuid.uuid4().hex[:10]}")
    payload["product_id"] = product_id
    ctx = JobContext(
        job_id=f"job-{uuid.uuid4().hex[:10]}",
        task_id=f"task-{uuid.uuid4().hex[:10]}",
        scene="S4",
        biz_id=product_id,
        payload=payload,
        data_version=payload.get("data_version"),
    )
    result = await handler.run(ctx)
    output_text = json.dumps(result.to_receipt_payload(), ensure_ascii=False, indent=2)
    print(output_text)
    if args.out_path is not None:
        args.out_path.parent.mkdir(parents=True, exist_ok=True)
        args.out_path.write_text(output_text, encoding="utf-8")
        print(f"已写入: {args.out_path}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input_path",
        nargs="?",
        type=Path,
        help="可选：JSON/YAML payload、标题文本文件或单张商品图片",
    )
    parser.add_argument("--title", default=None, help="商品标题；指定后覆盖输入文件中的 title")
    parser.add_argument(
        "--image",
        dest="images",
        action="append",
        default=[],
        help="商品图片路径或 http(s) URL，可重复指定，最多 5 张",
    )
    parser.add_argument("--product-id", default=None, help="可选商品 ID")
    parser.add_argument(
        "--allow-domain",
        dest="allow_domains",
        action="append",
        default=[],
        help="仅本次测试允许的远程图片域名，可重复指定",
    )
    parser.add_argument("--env", default=None, help="配置环境：dev/staging/prod，默认读取 APP_ENV")
    parser.add_argument("--out", dest="out_path", type=Path, default=None, help="结果 JSON 路径")
    args = parser.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
