"""S1/S2 MVP CLI 共用装配（兼容层）。

实现已迁至 `label_agent.bootstrap.mvp_scene_factory`，本模块仅再导出，
避免脚本与 JobWorker 两套装配逻辑分叉。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from label_agent.bootstrap.mvp_scene_factory import (  # noqa: F401
    FIXTURES_DIR,
    REPO_ROOT,
    build_domain_index,
    build_embedding_provider,
    build_evidence_matcher,
    build_llm_gateway,
    load_yaml_config,
    require_openai_api_key,
)
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.perception.extractors.base import AttachmentKind
from label_agent.perception.input_router import InputRouter
from label_agent.perception.media_guard import MediaGuard
from label_agent.perception.text.normalizer import TextNormalizer

_PAYLOAD_SUFFIXES = {".json", ".yaml", ".yml"}
_ATTACHMENT_TYPE = {
    AttachmentKind.TEXT: "text",
    AttachmentKind.IMAGE: "image",
    AttachmentKind.VIDEO: "video",
    AttachmentKind.PDF: "pdf",
    AttachmentKind.DOCX: "docx",
    AttachmentKind.DOC: "doc",
}


def build_text_normalizer() -> TextNormalizer:
    """创建默认 TextNormalizer。"""
    return TextNormalizer()


def build_media_guard() -> MediaGuard:
    """创建 MVP 用 MediaGuard（远程 URI 默认空白名单）。"""
    return MediaGuard(allowed_domains=set(), max_bytes=20 * 1024 * 1024)


def build_prompt_manager() -> PromptManager:
    """创建 PromptManager。"""
    return PromptManager()


def read_input_payload(path: Path) -> dict[str, Any]:
    """把单个本地输入路径解析为 JobContext.payload。"""
    suffix = path.suffix.lower()
    if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        return {"image_path": str(path)}
    if suffix in {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}:
        return {"video_path": str(path)}
    if suffix == ".pdf":
        return {"input_path": str(path), "pdf_path": str(path)}
    if suffix == ".docx":
        return {"input_path": str(path), "docx_path": str(path)}
    if suffix == ".doc":
        return {"input_path": str(path)}
    if suffix in _PAYLOAD_SUFFIXES:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise SystemExit("JSON/YAML 输入必须是对象")
        return data
    return {"text": path.read_text(encoding="utf-8")}


def read_input_payloads(paths: list[Path]) -> dict[str, Any]:
    """把一个或多个本地路径解析为 JobContext.payload。

    单文件保持原字段（image_path / input_path / 或 JSON payload）。
    多文件组装为 attachments[]，由 InputRouter 按顺序抽取后合并文本。
    """
    if not paths:
        raise SystemExit("至少提供一个输入路径")
    if len(paths) == 1:
        return read_input_payload(paths[0])
    if any(path.suffix.lower() in _PAYLOAD_SUFFIXES for path in paths):
        raise SystemExit("多文件输入不支持混入 JSON/YAML payload，请只传材料文件")
    router = InputRouter()
    attachments: list[dict[str, str]] = []
    for path in paths:
        kind = router.detect_kind_from_path(str(path))
        if kind is None:
            raise SystemExit(f"无法识别附件类型: {path}")
        attachments.append({"type": _ATTACHMENT_TYPE[kind], "path": str(path)})
    return {"attachments": attachments}
