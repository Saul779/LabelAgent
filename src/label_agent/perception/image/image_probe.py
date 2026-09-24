"""图片基础画像：真实解码、尺寸/DPI、像素上限与轻量清晰度评分。"""

from __future__ import annotations

import tempfile
import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import fitz
from PIL import Image, ImageOps, UnidentifiedImageError

from label_agent.core.exceptions import NonRetryableError

_PROBE_VERSION = "fitz-pillow-image-probe-v2"


@dataclass(frozen=True)
class ImageProfile:
    width: int
    height: int
    dpi_x: float | None
    dpi_y: float | None
    orientation: int | None
    sharpness_score: float


class ImageProbe:
    """使用 PyMuPDF 解码常规图片，并通过 Pillow 兼容 WebP。"""

    def __init__(self, *, max_pixels: int = 40_000_000) -> None:
        self._max_pixels = max(1, max_pixels)

    @property
    def version(self) -> str:
        return _PROBE_VERSION

    def inspect(self, path: Path) -> ImageProfile:
        try:
            pixmap = fitz.Pixmap(str(path))
        except Exception as fitz_exc:  # noqa: BLE001
            return self._inspect_with_pillow(path, fitz_exc)
        try:
            width = int(pixmap.width)
            height = int(pixmap.height)
            self._validate_dimensions(width, height)
            return ImageProfile(
                width=width,
                height=height,
                dpi_x=_positive_or_none(pixmap.xres),
                dpi_y=_positive_or_none(pixmap.yres),
                orientation=None,
                sharpness_score=_estimate_sharpness(pixmap),
            )
        finally:
            pixmap = None

    def prepare_for_processing(self, path: Path) -> tuple[Path, bool]:
        """必要时将 WebP 首帧转成临时 PNG，供 OCR 与 Vision 稳定处理。"""
        if path.suffix.lower() != ".webp":
            return path, False

        try:
            pixmap = fitz.Pixmap(str(path))
        except Exception:  # noqa: BLE001 - 当前 MuPDF 可能未编译 WebP 解码能力
            pass
        else:
            del pixmap
            return path, False

        temporary_path: Path | None = None
        try:
            with _pillow_decompression_guard(), Image.open(path) as image:
                self._validate_dimensions(*image.size)
                image.seek(0)
                frame = ImageOps.exif_transpose(image)
                normalized = _flatten_transparency(frame)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temporary:
                    temporary_path = Path(temporary.name)
                normalized.save(temporary_path, format="PNG")
            return temporary_path, True
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            UnidentifiedImageError,
            OSError,
            ValueError,
        ) as exc:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise NonRetryableError(f"无法解码 WebP 图片: {path} ({exc})") from exc

    def _inspect_with_pillow(self, path: Path, fitz_exc: Exception) -> ImageProfile:
        try:
            with _pillow_decompression_guard(), Image.open(path) as image:
                width, height = image.size
                self._validate_dimensions(width, height)
                image.seek(0)
                rgb_image = ImageOps.exif_transpose(image).convert("RGB")
                dpi_x, dpi_y = _pillow_dpi(image.info.get("dpi"))
                return ImageProfile(
                    width=int(rgb_image.width),
                    height=int(rgb_image.height),
                    dpi_x=dpi_x,
                    dpi_y=dpi_y,
                    orientation=_pillow_orientation(image),
                    sharpness_score=_estimate_sampled_bytes(
                        rgb_image.tobytes(),
                        channels=3,
                        width=rgb_image.width,
                        height=rgb_image.height,
                    ),
                )
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            UnidentifiedImageError,
            OSError,
            ValueError,
        ) as exc:
            raise NonRetryableError(
                f"无法解码图片: {path} (PyMuPDF: {fitz_exc}; Pillow: {exc})"
            ) from exc

    def _validate_dimensions(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise NonRetryableError("图片宽高无效")
        pixels = width * height
        if pixels > self._max_pixels:
            raise NonRetryableError(f"图片像素数超限: {pixels} > {self._max_pixels}")


def _positive_or_none(value: int | float | None) -> float | None:
    if value is None or float(value) <= 0:
        return None
    return float(value)


def _estimate_sharpness(pixmap: fitz.Pixmap) -> float:
    """用稀疏相邻像素亮度差给出 0~1 的轻量清晰度代理分数。"""
    return _estimate_sampled_bytes(
        pixmap.samples,
        channels=max(1, int(pixmap.n)),
        width=pixmap.width,
        height=pixmap.height,
    )


def _estimate_sampled_bytes(samples: bytes, *, channels: int, width: int, height: int) -> float:
    pixel_count = width * height
    if not samples or pixel_count < 2:
        return 0.0
    stride_pixels = max(1, pixel_count // 4096)
    total_diff = 0.0
    comparisons = 0
    previous: float | None = None
    for pixel_index in range(0, pixel_count, stride_pixels):
        offset = pixel_index * channels
        pixel = samples[offset : offset + min(3, channels)]
        if not pixel:
            continue
        luminance = sum(pixel) / len(pixel)
        if previous is not None:
            total_diff += abs(luminance - previous)
            comparisons += 1
        previous = luminance
    if comparisons == 0:
        return 0.0
    return min(1.0, max(0.0, total_diff / comparisons / 64.0))


def _flatten_transparency(image: Image.Image) -> Image.Image:
    """将透明区域铺成白色，避免 OCR 把透明像素解释成黑色背景。"""
    rgba = image.convert("RGBA")
    background = Image.new("RGBA", rgba.size, "white")
    return Image.alpha_composite(background, rgba).convert("RGB")


def _pillow_dpi(raw_dpi: object) -> tuple[float | None, float | None]:
    if isinstance(raw_dpi, int | float):
        value = _positive_or_none(raw_dpi)
        return value, value
    if isinstance(raw_dpi, list | tuple) and len(raw_dpi) >= 2:
        try:
            return _positive_or_none(raw_dpi[0]), _positive_or_none(raw_dpi[1])
        except (TypeError, ValueError):
            return None, None
    return None, None


def _pillow_orientation(image: Image.Image) -> int | None:
    try:
        orientation = image.getexif().get(274)
    except (AttributeError, OSError, ValueError):
        return None
    return int(orientation) if isinstance(orientation, int) else None


@contextmanager
def _pillow_decompression_guard() -> Iterator[None]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        yield
