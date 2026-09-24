"""ObjectStorageClient：下载媒体资源，配合 perception.media_guard 做安全校验。"""

from __future__ import annotations

from label_agent.settings import Settings


class ObjectStorageClient:
    """对象存储客户端：读写媒体资产。"""

    def __init__(self, settings: Settings) -> None:
        """注入存储桶与鉴权配置。"""
        self._endpoint = settings.object_storage_endpoint
        self._bucket = settings.object_storage_bucket

    async def download(self, uri: str) -> bytes:
        raise NotImplementedError
