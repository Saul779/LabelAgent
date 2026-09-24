"""图片 Artifact 提取：下载/校验/生成 image_hash（依赖 MediaGuard 做 SSRF/大小校验）。"""

from __future__ import annotations

from label_agent.domain.models.content import ImageArtifact
from label_agent.perception.media_guard import MediaGuard


class ImageArtifactExtractor:
    """图片 Artifact 提取器：经 MediaGuard 校验 URI 安全后下载图片并生成 image_hash。"""

    def __init__(self, media_guard: MediaGuard) -> None:
        """初始化图片产物抽取器依赖。"""
        self._media_guard = media_guard

    async def extract(self, image_uri: str) -> ImageArtifact:
        """校验 image_uri 是否允许访问，通过后提取为 ImageArtifact。"""
        self._media_guard.assert_uri_allowed(image_uri)
        raise NotImplementedError
