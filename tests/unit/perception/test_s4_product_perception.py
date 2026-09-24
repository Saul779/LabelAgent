"""S4 商品图片 OCR + Vision 感知测试。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from PIL import Image

from label_agent.core.context import JobContext
from label_agent.domain.models.content import OcrSegment
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.inference.providers.base import ModelCompletionResult
from label_agent.perception.media_guard import MediaGuard
from label_agent.scenarios.s4_product.perception import (
    ProductPerceptionService,
    S4InputError,
)


class _Ocr:
    async def recognize(self, image_uri: str, *, asset_id: str = ""):
        assert Path(image_uri).suffix == ".png"
        return [OcrSegment(asset_id=asset_id, text="苹果 500g", confidence=0.99)]


class _VisionGateway:
    async def complete(self, request, model_alias=None):
        _ = model_alias
        assert request.image_urls and request.image_urls[0].startswith("data:image/png;base64,")
        return ModelCompletionResult(
            raw_text="图片中是袋装红苹果",
            model_name="vision-model",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
        )


def _service() -> ProductPerceptionService:
    return ProductPerceptionService(
        _VisionGateway(),  # type: ignore[arg-type]
        PromptManager(),
        _Ocr(),  # type: ignore[arg-type]
        MediaGuard(allowed_domains=set(), max_bytes=1024 * 1024),
    )


def _ctx(payload: dict) -> JobContext:
    return JobContext(
        job_id="job-s4-image",
        task_id="task-s4-image",
        scene="S4",
        biz_id="product-image",
        payload=payload,
    )


def test_local_image_runs_ocr_and_vision(tmp_path: Path) -> None:
    image_path = tmp_path / "product.webp"
    Image.new("RGB", (20, 20), color="red").save(image_path, format="WEBP")

    result = asyncio.run(
        _service().perceive(_ctx({"title": "新鲜红苹果", "images": [str(image_path)]}))
    )

    assert result.title == "新鲜红苹果"
    assert len(result.images) == 1
    assert result.images[0].ocr_text == "苹果 500g"
    assert result.images[0].vision_text == "图片中是袋装红苹果"
    assert result.images[0].ocr_succeeded is True
    assert result.images[0].vision_succeeded is True


def test_title_and_images_cannot_both_be_empty() -> None:
    with pytest.raises(S4InputError):
        asyncio.run(_service().perceive(_ctx({"title": "", "images": []})))


def test_rejects_more_than_five_images() -> None:
    with pytest.raises(S4InputError):
        asyncio.run(
            _service().perceive(
                _ctx({"title": "商品", "images": [f"image-{index}.jpg" for index in range(6)]})
            )
        )
