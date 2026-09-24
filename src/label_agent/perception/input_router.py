"""输入路由：将异构 JobContext.payload 归一为 AttachmentRef 列表。

支持显式 attachments 数组与历史兼容字段（text / image_path / video_path / input_path 等），
按后缀或声明 type 判定 AttachmentKind，供 CertificateContentLoader / ContentBundleBuilder 分发。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from label_agent.perception.extractors.base import AttachmentKind, AttachmentRef

_ROUTER_VERSION = "v2"

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm", ".m4v"}
_TEXT_SUFFIXES = {".txt", ".md", ".csv", ".log"}
_PDF_SUFFIXES = {".pdf"}
_DOCX_SUFFIXES = {".docx"}
_DOC_SUFFIXES = {".doc"}

_TYPE_ALIASES: dict[str, AttachmentKind] = {
    "text": AttachmentKind.TEXT,
    "txt": AttachmentKind.TEXT,
    "image": AttachmentKind.IMAGE,
    "img": AttachmentKind.IMAGE,
    "photo": AttachmentKind.IMAGE,
    "video": AttachmentKind.VIDEO,
    "mp4": AttachmentKind.VIDEO,
    "pdf": AttachmentKind.PDF,
    "docx": AttachmentKind.DOCX,
    "doc": AttachmentKind.DOC,
}


class InputRouter:
    """S1/S2 感知输入路由器。

    将 payload 中可能出现的多种字段形态解析为有序 AttachmentRef 列表：
    - 优先解析 attachments[]（推荐协议）；
    - 再兼容 text/raw_text/content、image_*、input_path/file_path/document_path；
    - 同一次请求可同时包含文本补充与一个或多个文件附件。
    """

    @property
    def version(self) -> str:
        """返回路由器实现版本号，写入 perception_versions.input_router。"""
        return _ROUTER_VERSION

    def route(self, payload: dict[str, Any] | None) -> list[AttachmentRef]:
        """解析 payload 并返回待处理附件列表（可能为空）。

        空 payload 返回空列表，由编排层判定是否抛出“缺少输入”错误。
        未知 type/后缀的附件会被跳过（不进入列表），避免误调度抽取器。
        """
        if not payload:
            return []

        refs: list[AttachmentRef] = []
        seen: set[tuple[str, str]] = set()

        def _add(ref: AttachmentRef) -> None:
            ref_key = f"inline:{hash(ref.inline_text)}" if ref.inline_text is not None else ref.ref
            key = (ref.kind.value, ref_key)
            if key in seen:
                return
            seen.add(key)
            refs.append(ref)

        attachments = payload.get("attachments")
        if isinstance(attachments, list):
            for index, item in enumerate(attachments):
                parsed = self._parse_attachment_item(item, index)
                if parsed is not None:
                    _add(parsed)

        for key in ("text", "raw_text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                _add(
                    AttachmentRef(
                        kind=AttachmentKind.TEXT,
                        ref=f"payload:{key}",
                        inline_text=value,
                        source_key=key,
                    )
                )
                break

        for key in ("image_path", "image_uri", "image_url"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                _add(
                    AttachmentRef(
                        kind=AttachmentKind.IMAGE,
                        ref=value.strip(),
                        source_key=key,
                    )
                )
                break

        for key in ("video_path", "video_uri", "video_url"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                _add(
                    AttachmentRef(
                        kind=AttachmentKind.VIDEO,
                        ref=value.strip(),
                        source_key=key,
                    )
                )
                break

        # 兼容历史字段 uri：按后缀推断 image/video，默认当作图片
        uri_value = payload.get("uri")
        if isinstance(uri_value, str) and uri_value.strip():
            uri_kind = self.detect_kind_from_path(uri_value.strip()) or AttachmentKind.IMAGE
            if uri_kind in {AttachmentKind.IMAGE, AttachmentKind.VIDEO}:
                _add(
                    AttachmentRef(
                        kind=uri_kind,
                        ref=uri_value.strip(),
                        source_key="uri",
                    )
                )

        for key in ("input_path", "file_path", "document_path", "pdf_path", "docx_path"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                path_kind = self.detect_kind_from_path(value.strip())
                if path_kind is not None:
                    _add(
                        AttachmentRef(
                            kind=path_kind,
                            ref=value.strip(),
                            source_key=key,
                        )
                    )
                break

        return refs

    def detect_kind_from_path(self, path_str: str) -> AttachmentKind | None:
        """根据路径后缀推断附件类型；无法识别时返回 None。

        用于 input_path 兼容字段与 CLI 本地文件路由。不打开文件、不做 magic bytes 检测
        （magic 校验留给各 Extractor / MediaGuard）。
        """
        suffix = Path(path_str).suffix.lower()
        if suffix in _IMAGE_SUFFIXES:
            return AttachmentKind.IMAGE
        if suffix in _VIDEO_SUFFIXES:
            return AttachmentKind.VIDEO
        if suffix in _PDF_SUFFIXES:
            return AttachmentKind.PDF
        if suffix in _DOCX_SUFFIXES:
            return AttachmentKind.DOCX
        if suffix in _DOC_SUFFIXES:
            return AttachmentKind.DOC
        if suffix in _TEXT_SUFFIXES:
            return AttachmentKind.TEXT
        return None

    def _parse_attachment_item(self, item: Any, index: int) -> AttachmentRef | None:
        """解析 attachments 数组中的单个元素为 AttachmentRef。

        支持 dict（含 type/path/uri/text）与纯字符串路径两种写法。
        无法识别类型时返回 None。
        """
        source_key = f"attachments[{index}]"
        if isinstance(item, str) and item.strip():
            path_kind = self.detect_kind_from_path(item.strip())
            if path_kind is None:
                return None
            return AttachmentRef(kind=path_kind, ref=item.strip(), source_key=source_key)

        if not isinstance(item, dict):
            return None

        declared = item.get("type") or item.get("kind") or item.get("mime")
        kind: AttachmentKind | None = None
        if isinstance(declared, str) and declared.strip():
            key = declared.strip().lower()
            if "/" in key:
                # 简单 MIME：application/pdf → pdf
                key = key.split("/", 1)[-1]
            kind = _TYPE_ALIASES.get(key)

        path_or_uri = None
        for key in (
            "path",
            "uri",
            "url",
            "file_path",
            "image_path",
            "image_uri",
            "video_path",
            "video_uri",
        ):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                path_or_uri = value.strip()
                break

        inline = item.get("text")
        if kind is None and isinstance(inline, str) and inline.strip():
            kind = AttachmentKind.TEXT
        if kind is None and path_or_uri:
            kind = self.detect_kind_from_path(path_or_uri)
        if kind is None:
            return None

        if kind == AttachmentKind.TEXT:
            text_value = inline if isinstance(inline, str) else None
            if text_value is None and path_or_uri:
                return AttachmentRef(
                    kind=kind,
                    ref=path_or_uri,
                    source_key=source_key,
                )
            if not text_value or not text_value.strip():
                return None
            return AttachmentRef(
                kind=kind,
                ref=path_or_uri or f"payload:{source_key}",
                inline_text=text_value,
                source_key=source_key,
            )

        if not path_or_uri:
            return None
        return AttachmentRef(kind=kind, ref=path_or_uri, source_key=source_key)
