"""S1/S2 HybridImageExtractor 单元测试。"""

from __future__ import annotations

import base64
from pathlib import Path

import fitz
import pytest
from PIL import Image

from label_agent.domain.models.content import OcrSegment
from label_agent.perception.extractors.base import (
    AttachmentKind,
    AttachmentRef,
    ExtractionResult,
)
from label_agent.perception.extractors.hybrid_image_extractor import HybridImageExtractor
from label_agent.perception.image.image_probe import ImageProbe
from label_agent.perception.media_guard import MediaGuard
from label_agent.utils.hashing import sha256_hex


def _make_png(path: Path, *, width: int = 320, height: int = 200) -> bytes:
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, width, height), False)
    pixmap.clear_with(255)
    pixmap.save(str(path))
    return path.read_bytes()


def _make_webp(path: Path, *, width: int = 320, height: int = 200) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    image.save(path, format="WEBP")
    return path.read_bytes()


class _FakeOcr:
    version = "fake-ocr-v1"

    def __init__(self, segments: list[OcrSegment] | None = None, *, fail: bool = False) -> None:
        self._segments = segments or []
        self._fail = fail
        self.last_image_uri = ""
        self.image_existed_during_recognition = False

    async def recognize(self, image_uri: str, *, asset_id: str = "") -> list[OcrSegment]:
        self.last_image_uri = image_uri
        self.image_existed_during_recognition = Path(image_uri).is_file()
        if self._fail:
            raise RuntimeError("ocr unavailable")
        return [segment.model_copy(update={"asset_id": asset_id}) for segment in self._segments]


class _FakeVision:
    def __init__(self, text: str = "视觉识别：软件工程师证书", *, fail: bool = False) -> None:
        self._text = text
        self._fail = fail
        self.last_context_hint = ""
        self.last_attachment_ref = ""
        self.image_existed_during_extraction = False

    async def extract(
        self, attachment: AttachmentRef, *, context_hint: str = ""
    ) -> ExtractionResult:
        self.last_attachment_ref = attachment.ref
        self.image_existed_during_extraction = Path(attachment.ref).is_file()
        self.last_context_hint = context_hint
        if self._fail:
            raise RuntimeError("vision unavailable")
        return ExtractionResult(
            text=self._text,
            successful_modality="image",
            perception_versions={"vision_prompt": "vision-v1"},
        )


def _extractor(ocr: _FakeOcr, vision: _FakeVision, **options) -> HybridImageExtractor:
    return HybridImageExtractor(
        image_vision_extractor=vision,  # type: ignore[arg-type]
        ocr_engine=ocr,  # type: ignore[arg-type]
        media_guard=MediaGuard(allowed_domains=set(), max_bytes=2 * 1024 * 1024),
        **options,
    )


@pytest.mark.asyncio
async def test_sparse_text_runs_ocr_and_vision_with_provenance(tmp_path: Path) -> None:
    image_path = tmp_path / "cert.png"
    _make_png(image_path)
    ocr = _FakeOcr(
        [
            OcrSegment(
                asset_id="",
                text="软件工程师职业资格证书",
                bbox=[20, 20, 260, 20, 260, 50, 20, 50],
                confidence=0.96,
            )
        ]
    )
    vision = _FakeVision()

    result = await _extractor(ocr, vision).extract(
        AttachmentRef(kind=AttachmentKind.IMAGE, ref=str(image_path))
    )

    assert "OCR感知文本" in result.text
    assert "Vision感知文本" in result.text
    assert result.successful_modality == "image_hybrid"
    assert result.successful_modalities == ["image_ocr", "image_vision"]
    assert [block.source_type for block in result.perception_text_blocks] == ["ocr", "vision"]
    assert result.ocr_segments[0].normalized_bbox == pytest.approx([0.0625, 0.1, 0.8125, 0.25])
    assert "软件工程师职业资格证书" in vision.last_context_hint
    artifact = result.image_artifacts[0]
    assert artifact.width == 320
    assert artifact.height == 200
    assert artifact.processing_route == "ocr_vision"


@pytest.mark.asyncio
async def test_no_text_uses_vision_only(tmp_path: Path) -> None:
    image_path = tmp_path / "photo.png"
    _make_png(image_path)
    result = await _extractor(_FakeOcr(), _FakeVision("视觉职业场景描述")).extract(
        AttachmentRef(kind=AttachmentKind.IMAGE, ref=str(image_path))
    )
    assert "视觉职业场景描述" in result.text
    assert result.ocr_segments == []
    assert result.image_artifacts[0].processing_route == "vision_only"
    assert result.image_artifacts[0].text_density == "none"


@pytest.mark.asyncio
async def test_ocr_failure_degrades_to_vision(tmp_path: Path) -> None:
    image_path = tmp_path / "cert.png"
    _make_png(image_path)
    result = await _extractor(_FakeOcr(fail=True), _FakeVision()).extract(
        AttachmentRef(kind=AttachmentKind.IMAGE, ref=str(image_path))
    )
    assert result.successful_modality == "image_hybrid"
    assert result.successful_modalities == ["image_vision"]
    assert result.failed_modalities == ["image_ocr"]


@pytest.mark.asyncio
async def test_vision_failure_degrades_to_ocr(tmp_path: Path) -> None:
    image_path = tmp_path / "cert.png"
    _make_png(image_path)
    ocr = _FakeOcr(
        [
            OcrSegment(
                asset_id="",
                text="Python技能证书",
                bbox=[10, 10, 200, 10, 200, 40, 10, 40],
                confidence=0.91,
            )
        ]
    )
    result = await _extractor(ocr, _FakeVision(fail=True)).extract(
        AttachmentRef(kind=AttachmentKind.IMAGE, ref=str(image_path))
    )
    assert "Python技能证书" in result.text
    assert result.successful_modalities == ["image_ocr"]
    assert result.failed_modalities == ["image_vision"]


@pytest.mark.asyncio
async def test_dense_text_marks_route_and_truncation(tmp_path: Path) -> None:
    image_path = tmp_path / "dense.png"
    _make_png(image_path)
    segments = [
        OcrSegment(
            asset_id="",
            text=f"文本{i}",
            bbox=[0, i * 10, 200, i * 10, 200, i * 10 + 8, 0, i * 10 + 8],
            confidence=0.9,
        )
        for i in range(4)
    ]
    result = await _extractor(
        _FakeOcr(segments),
        _FakeVision(),
        dense_region_count=4,
    ).extract(AttachmentRef(kind=AttachmentKind.IMAGE, ref=str(image_path)))
    assert result.image_artifacts[0].processing_route == "dense_ocr_vision"
    assert "dense_text_detected" in result.truncation_flags


@pytest.mark.asyncio
async def test_data_url_is_materialized_for_ocr(tmp_path: Path) -> None:
    image_path = tmp_path / "data.png"
    content = _make_png(image_path)
    data_url = "data:image/png;base64," + base64.b64encode(content).decode("ascii")
    result = await _extractor(_FakeOcr(), _FakeVision()).extract(
        AttachmentRef(kind=AttachmentKind.IMAGE, ref=data_url)
    )
    assert result.image_artifacts[0].width == 320
    assert result.successful_modalities == ["image_vision"]


def test_probe_rejects_excessive_pixels(tmp_path: Path) -> None:
    image_path = tmp_path / "large.png"
    _make_png(image_path, width=101, height=100)
    with pytest.raises(Exception, match="像素数超限"):
        ImageProbe(max_pixels=10_000).inspect(image_path)


def test_probe_inspects_webp_with_pillow_fallback(tmp_path: Path) -> None:
    image_path = tmp_path / "certificate.webp"
    _make_webp(image_path, width=64, height=32)

    profile = ImageProbe().inspect(image_path)

    assert profile.width == 64
    assert profile.height == 32
    assert 0.0 <= profile.sharpness_score <= 1.0


def test_probe_rejects_excessive_webp_pixels_before_conversion(tmp_path: Path) -> None:
    image_path = tmp_path / "large.webp"
    _make_webp(image_path, width=101, height=100)

    with pytest.raises(Exception, match="像素数超限"):
        ImageProbe(max_pixels=10_000).prepare_for_processing(image_path)


@pytest.mark.asyncio
async def test_webp_is_converted_for_ocr_and_vision_without_changing_artifact(
    tmp_path: Path,
) -> None:
    image_path = tmp_path / "certificate.webp"
    original_bytes = _make_webp(image_path, width=64, height=32)
    ocr = _FakeOcr()
    vision = _FakeVision()

    result = await _extractor(ocr, vision).extract(
        AttachmentRef(kind=AttachmentKind.IMAGE, ref=str(image_path))
    )

    assert result.successful_modalities == ["image_vision"]
    assert ocr.image_existed_during_recognition
    assert vision.image_existed_during_extraction
    assert Path(ocr.last_image_uri).suffix == ".png"
    assert vision.last_attachment_ref == ocr.last_image_uri
    assert not Path(ocr.last_image_uri).exists()
    artifact = result.image_artifacts[0]
    assert artifact.uri == str(image_path)
    assert artifact.image_hash == sha256_hex(original_bytes)
    assert artifact.width == 64
    assert artifact.height == 32
