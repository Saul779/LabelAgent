"""将本地路径 / HTTP(S) URI 解析为本地可读文件，供视频抽帧与 ASR 使用。"""

from __future__ import annotations

import base64
import binascii
import logging
import tempfile
from pathlib import Path
from urllib.parse import unquote_to_bytes, urlparse

import httpx

from label_agent.core.exceptions import NonRetryableError, SsrfProtectionError
from label_agent.perception.media_guard import MediaGuard

logger = logging.getLogger(__name__)


def resolve_local_path(
    uri: str,
    *,
    media_guard: MediaGuard | None = None,
    suffix: str = "",
) -> tuple[Path, bool]:
    """解析媒体引用为本地 Path。

    返回 (path, is_temporary)：is_temporary=True 时由调用方负责清理临时文件。
    本地已存在文件直接返回；HTTP(S) 经 MediaGuard 校验后下载到临时文件。
    """
    if uri.startswith(("http://", "https://")):
        if media_guard is not None:
            media_guard.assert_uri_allowed(uri)
        return (
            _download_to_temp(
                uri,
                suffix=suffix or _suffix_from_uri(uri),
                media_guard=media_guard,
            ),
            True,
        )

    if uri.startswith("data:"):
        return (
            _decode_data_url_to_temp(uri, suffix=suffix, media_guard=media_guard),
            True,
        )

    path = Path(uri)
    if path.exists() and path.is_file():
        if media_guard is not None:
            media_guard.assert_size_allowed(path.stat().st_size)
        return path, False

    raise NonRetryableError(f"无法解析媒体引用: {uri}")


def _suffix_from_uri(uri: str) -> str:
    """从 URI path 提取后缀；无后缀时返回空串。"""
    parsed = urlparse(uri)
    return Path(parsed.path).suffix.lower()


def _download_to_temp(
    uri: str,
    *,
    suffix: str,
    media_guard: MediaGuard | None,
) -> Path:
    """同步下载远程媒体到临时文件。"""
    try:
        with (
            httpx.Client(timeout=60.0, follow_redirects=True) as client,
            client.stream("GET", uri) as response,
        ):
            response.raise_for_status()
            declared = response.headers.get("content-length")
            if declared and media_guard is not None:
                media_guard.assert_size_allowed(int(declared))
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if media_guard is not None:
                    media_guard.assert_size_allowed(total)
                chunks.append(chunk)
            content = b"".join(chunks)
    except SsrfProtectionError:
        raise
    except Exception as exc:  # noqa: BLE001 — 下载失败统一转为不可重试/业务错误由上层分类
        raise NonRetryableError(f"下载媒体失败: {uri} ({exc})") from exc

    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - 需要 delete=False 持久化路径
        delete=False,
        suffix=suffix or ".bin",
    )
    try:
        tmp.write(content)
        tmp.flush()
    finally:
        tmp.close()
    logger.info("媒体已下载到临时文件 path=%s bytes=%s", tmp.name, len(content))
    return Path(tmp.name)


def _decode_data_url_to_temp(
    uri: str,
    *,
    suffix: str,
    media_guard: MediaGuard | None,
) -> Path:
    """安全解码 data URL 到临时文件，并执行字节上限校验。"""
    try:
        header, payload = uri.split(",", 1)
        is_base64 = header.lower().endswith(";base64")
        content = (
            base64.b64decode(payload, validate=True) if is_base64 else unquote_to_bytes(payload)
        )
    except (binascii.Error, ValueError, TypeError) as exc:
        raise NonRetryableError("无法解析 data URL") from exc
    if media_guard is not None:
        media_guard.assert_size_allowed(len(content))
    resolved_suffix = suffix or _suffix_from_data_header(header)
    tmp = tempfile.NamedTemporaryFile(  # noqa: SIM115 - 需要 delete=False 持久化路径
        delete=False,
        suffix=resolved_suffix or ".bin",
    )
    try:
        tmp.write(content)
        tmp.flush()
    finally:
        tmp.close()
    return Path(tmp.name)


def _suffix_from_data_header(header: str) -> str:
    media_type = header[5:].split(";", 1)[0].lower()
    return {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/bmp": ".bmp",
    }.get(media_type, "")
