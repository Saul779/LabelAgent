"""OCR 引擎：PaddleOCR 实现，供 S3 视频帧感知与 tools/ocr_tool 复用。"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from label_agent.domain.models.content import OcrSegment

logger = logging.getLogger(__name__)

_ENGINE_VERSION = "paddleocr-v2"


class OcrEngine:
    """基于 PaddleOCR 的文字识别引擎。

    构造时惰性加载模型；recognize 在线程池中执行，避免阻塞事件循环。
    """

    def __init__(self, *, lang: str = "ch", use_angle_cls: bool = True) -> None:
        """初始化 OCR 配置；模型在首次 recognize 时加载。"""
        self._lang = lang
        self._use_angle_cls = use_angle_cls
        self._ocr: Any | None = None
        self._paddleocr_major = 0
        self._recognize_lock = asyncio.Lock()

    @property
    def version(self) -> str:
        """引擎版本号，写入 perception_versions。"""
        return _ENGINE_VERSION

    def _ensure_ocr(self) -> Any:
        """惰性创建 PaddleOCR 实例。"""
        if self._ocr is not None:
            return self._ocr
        try:
            import paddleocr
            from paddleocr import PaddleOCR
        except ImportError as exc:  # pragma: no cover - 依赖缺失时的明确报错
            raise RuntimeError(
                "未安装 paddleocr，请执行: pip install -r requirements-perception.txt"
            ) from exc
        self._paddleocr_major = _major_version(getattr(paddleocr, "__version__", "0"))
        if self._paddleocr_major >= 3:
            self._ocr = PaddleOCR(
                lang=self._lang,
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=self._use_angle_cls,
            )
        else:  # pragma: no cover - 仅用于兼容仍在使用 PaddleOCR 2.x 的部署
            self._ocr = PaddleOCR(
                use_angle_cls=self._use_angle_cls,
                lang=self._lang,
                show_log=False,
            )
        return self._ocr

    async def recognize(self, image_uri: str, *, asset_id: str = "") -> list[OcrSegment]:
        """对本地图片路径执行 OCR，返回带 bbox 的文本片段。

        image_uri 须为本地可读文件路径（视频帧由 FrameSampler 落盘）。
        asset_id 为空时使用文件名 stem。
        """
        resolved_asset = asset_id or _default_asset_id(image_uri)
        async with self._recognize_lock:
            return await asyncio.to_thread(self._recognize_sync, image_uri, resolved_asset)

    def _recognize_sync(self, image_path: str, asset_id: str) -> list[OcrSegment]:
        """同步 OCR；解析 PaddleOCR 返回结构为 OcrSegment 列表。"""
        ocr = self._ensure_ocr()
        if self._paddleocr_major >= 3:
            return _parse_v3_results(ocr.predict(image_path), asset_id)
        raw = ocr.ocr(image_path, cls=self._use_angle_cls)
        segments: list[OcrSegment] = []
        if not raw:
            return segments
        # PaddleOCR 对单图返回 [lines]；lines 为 None 表示无检测结果
        pages = raw if isinstance(raw, list) else [raw]
        for page in pages:
            if not page:
                continue
            for line in page:
                if not line or len(line) < 2:
                    continue
                box, payload = line[0], line[1]
                text = payload[0] if isinstance(payload, list | tuple) else str(payload)
                confidence = None
                if isinstance(payload, list | tuple) and len(payload) > 1:
                    try:
                        confidence = min(1.0, max(0.0, float(payload[1])))
                    except (TypeError, ValueError):
                        confidence = None
                if not str(text).strip():
                    continue
                bbox = _flatten_box(box)
                segments.append(
                    OcrSegment(
                        asset_id=asset_id,
                        text=str(text).strip(),
                        bbox=bbox,
                        confidence=confidence,
                        reading_order=len(segments),
                    )
                )
        logger.debug("OCR 完成 path=%s segments=%s", image_path, len(segments))
        return segments


def _parse_v3_results(results: Any, asset_id: str) -> list[OcrSegment]:
    """解析 PaddleOCR 3.x OCRResult 中的文字、置信度和多边形坐标。"""
    segments: list[OcrSegment] = []
    for result in results or []:
        if not hasattr(result, "get"):
            continue
        texts = result.get("rec_texts") or []
        scores = result.get("rec_scores") or []
        polygons = result.get("rec_polys") or result.get("dt_polys") or []
        for index, text in enumerate(texts):
            if not str(text).strip():
                continue
            confidence = _confidence_at(scores, index)
            box = polygons[index] if index < len(polygons) else []
            segments.append(
                OcrSegment(
                    asset_id=asset_id,
                    text=str(text).strip(),
                    bbox=_flatten_box(box),
                    confidence=confidence,
                    reading_order=len(segments),
                )
            )
    logger.debug("PaddleOCR 3.x 完成 asset_id=%s segments=%s", asset_id, len(segments))
    return segments


def _confidence_at(scores: Any, index: int) -> float | None:
    try:
        return min(1.0, max(0.0, float(scores[index])))
    except (IndexError, TypeError, ValueError):
        return None


def _major_version(version: str) -> int:
    try:
        return int(version.split(".", 1)[0])
    except (TypeError, ValueError):
        return 0


def _default_asset_id(path: str) -> str:
    """从路径提取 stem，供默认 asset_id 使用。"""
    from pathlib import Path

    return Path(path).stem


def _flatten_box(box: Any) -> list[float]:
    """将 Paddle 四点框 [[x,y],...] 展平为 float 列表；无法解析则返回空列表。"""
    try:
        return [float(coord) for point in box for coord in point]
    except (TypeError, ValueError):
        return []
