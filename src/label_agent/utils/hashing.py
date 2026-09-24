"""内容 Hash 工具：content_hash/payload_hash/image_hash 统一使用 sha256。"""

from __future__ import annotations

import hashlib


def sha256_hex(data: bytes | str) -> str:
    """计算字节或字符串的 SHA-256 十六进制摘要。"""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return f"sha256:{hashlib.sha256(data).hexdigest()}"
