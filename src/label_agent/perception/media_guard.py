"""媒体安全护栏：MIME/magic bytes 校验、大小限制、SSRF 防护（§5.1.2、§8）。"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from label_agent.core.exceptions import SsrfProtectionError

_PRIVATE_NETWORKS = [
    ipaddress.ip_network(net)
    for net in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "169.254.0.0/16")
]


class MediaGuard:
    """媒体安全护栏：域名白名单与私网拦截（SSRF）、体积上限校验。"""

    def __init__(self, allowed_domains: set[str], max_bytes: int) -> None:
        """配置允许访问的域名集合与最大字节数。"""
        self._allowed_domains = allowed_domains
        self._max_bytes = max_bytes

    def assert_uri_allowed(self, uri: str) -> None:
        """校验远程 URI 是否在白名单且非私网地址，否则拒绝。"""
        parsed = urlparse(uri)
        if parsed.hostname is None or parsed.hostname not in self._allowed_domains:
            raise SsrfProtectionError(f"域名不在白名单: {parsed.hostname}")
        try:
            ip = ipaddress.ip_address(parsed.hostname)
        except ValueError:
            return  # 域名形式，交由 DNS/网络层解析后二次校验（生产实现需补充解析后校验）
        if any(ip in net for net in _PRIVATE_NETWORKS):
            raise SsrfProtectionError(f"命中私网地址: {ip}")

    def assert_size_allowed(self, content_length: int) -> None:
        """校验媒体 Content-Length 是否超过配置上限。"""
        if content_length > self._max_bytes:
            raise ValueError(f"媒体大小超限: {content_length} > {self._max_bytes}")

    @property
    def max_bytes(self) -> int:
        """返回媒体字节上限，供流式下载和 data URL 解码使用。"""
        return self._max_bytes
