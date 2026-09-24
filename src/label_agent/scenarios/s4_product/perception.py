"""S4 商品图片 OCR + Vision 并行感知。"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import logging
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from PIL import Image

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.s4_product import (
    ProductImageObservation,
    ProductPerception,
)
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.inference.providers.base import ModelCompletionRequest
from label_agent.perception.image.ocr import OcrEngine
from label_agent.perception.media_guard import MediaGuard

logger = logging.getLogger(__name__)


class S4InputError(NonRetryableError):
    error_code = "S4_INVALID_INPUT"


@dataclass(frozen=True)
class _PreparedImage:
    source_ref: str
    local_path: Path
    vision_url: str
    cleanup_dir: Path | None


class ProductPerceptionService:
    """归一化标题/图片，并对每张图片并行执行 OCR 与视觉理解。"""

    def __init__(
        self,
        llm_gateway: LlmGateway,
        prompt_manager: PromptManager,
        ocr_engine: OcrEngine,
        media_guard: MediaGuard,
        *,
        vision_prompt_version: str = "s4-vision-v1",
        max_images: int = 5,
        request_timeout_sec: float = 30.0,
    ) -> None:
        self._llm_gateway = llm_gateway
        self._prompt_manager = prompt_manager
        self._ocr_engine = ocr_engine
        self._media_guard = media_guard
        self._vision_prompt_version = vision_prompt_version
        self._max_images = max_images
        self._request_timeout_sec = request_timeout_sec

    async def perceive(self, ctx: JobContext) -> ProductPerception:
        payload = ctx.payload or {}
        title = _first_text(payload, "title", "product_title")
        image_refs = _image_refs(payload)
        if len(image_refs) > self._max_images:
            raise S4InputError(f"S4 图片数量不能超过 {self._max_images} 张")
        if not title and not image_refs:
            raise S4InputError("S4 标题和图片不能同时为空")

        observations: list[ProductImageObservation] = []
        failed: list[str] = []
        results = await asyncio.gather(
            *[self._perceive_image(ref, title=title) for ref in image_refs],
            return_exceptions=True,
        )
        for ref, result in zip(image_refs, results, strict=True):
            if isinstance(result, BaseException):
                logger.warning("S4 商品图片感知失败 ref=%s err=%s", ref, result)
                failed.append(ref)
                continue
            observations.append(result)
            if not result.ocr_succeeded and not result.vision_succeeded:
                failed.append(ref)

        if not title and not any(
            item.ocr_succeeded or item.vision_succeeded for item in observations
        ):
            raise S4InputError("S4 所有商品图片均无法解析且未提供标题")
        return ProductPerception(title=title, images=observations, failed_image_refs=failed)

    async def _perceive_image(self, ref: str, *, title: str) -> ProductImageObservation:
        prepared = await self._prepare_image(ref)
        asset_id = hashlib.sha256(ref.encode("utf-8")).hexdigest()[:16]
        try:
            gathered = await asyncio.gather(
                self._ocr(prepared.local_path, asset_id),
                self._vision(prepared.vision_url, title=title),
                return_exceptions=True,
            )
            ocr_outcome: Any = gathered[0]
            vision_outcome: Any = gathered[1]
            ocr_text = ""
            vision_text = ""
            if not isinstance(ocr_outcome, BaseException):
                ocr_text = "\n".join(segment.text for segment in ocr_outcome if segment.text)
            else:
                logger.warning("S4 OCR 降级 ref=%s err=%s", ref, ocr_outcome)
            if not isinstance(vision_outcome, BaseException):
                vision_text = vision_outcome
            else:
                logger.warning("S4 Vision 降级 ref=%s err=%s", ref, vision_outcome)
            return ProductImageObservation(
                asset_id=asset_id,
                source_ref=ref,
                ocr_text=ocr_text,
                vision_text=vision_text,
                ocr_succeeded=not isinstance(ocr_outcome, BaseException),
                vision_succeeded=not isinstance(vision_outcome, BaseException),
            )
        finally:
            if prepared.cleanup_dir is not None:
                shutil.rmtree(prepared.cleanup_dir, ignore_errors=True)

    async def _ocr(self, path: Path, asset_id: str):
        return await self._ocr_engine.recognize(str(path), asset_id=asset_id)

    async def _vision(self, image_url: str, *, title: str) -> str:
        system_prompt, user_prompt = self._prompt_manager.render(
            scene="s4",
            prompt_version=self._vision_prompt_version,
            variables={"product_title": title},
        )
        result = await self._llm_gateway.complete(
            ModelCompletionRequest(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                image_urls=[image_url],
                temperature=0.0,
                max_tokens=800,
            )
        )
        return result.raw_text.strip()

    async def _prepare_image(self, ref: str) -> _PreparedImage:
        if ref.startswith("data:"):
            try:
                header, encoded = ref.split(",", 1)
                if ";base64" not in header:
                    raise ValueError("仅支持 base64 data URL")
                content = base64.b64decode(encoded, validate=True)
            except (ValueError, binascii.Error) as exc:
                raise S4InputError(f"非法图片 data URL: {exc}") from exc
            self._media_guard.assert_size_allowed(len(content))
            return await asyncio.to_thread(self._normalize_bytes, content, ref)

        if ref.startswith(("http://", "https://")):
            self._media_guard.assert_uri_allowed(ref)
            async with httpx.AsyncClient(timeout=self._request_timeout_sec) as client:
                response = await client.get(ref, follow_redirects=False)
            if response.status_code >= 400:
                raise S4InputError(f"商品图片下载失败: HTTP {response.status_code}")
            self._media_guard.assert_size_allowed(len(response.content))
            return await asyncio.to_thread(self._normalize_bytes, response.content, ref)

        path = Path(ref)
        if not path.exists() or not path.is_file():
            raise S4InputError(f"商品图片不存在: {ref}")
        self._media_guard.assert_size_allowed(path.stat().st_size)
        return await asyncio.to_thread(self._normalize_bytes, path.read_bytes(), ref)

    @staticmethod
    def _normalize_bytes(content: bytes, source_ref: str) -> _PreparedImage:
        temp_dir = Path(tempfile.mkdtemp(prefix="label-agent-s4-"))
        output = temp_dir / "normalized.png"
        try:
            from io import BytesIO

            with Image.open(BytesIO(content)) as image:
                image.seek(0)  # GIF 只取首帧；其他 Pillow 可读格式统一转 PNG。
                converted = image.convert("RGB")
                converted.save(output, format="PNG")
            encoded = base64.b64encode(output.read_bytes()).decode("ascii")
            return _PreparedImage(
                source_ref=source_ref,
                local_path=output,
                vision_url=f"data:image/png;base64,{encoded}",
                cleanup_dir=temp_dir,
            )
        except Exception as exc:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise S4InputError(f"不支持或损坏的商品图片: {exc}") from exc


def _first_text(payload: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _image_refs(payload: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    images = payload.get("images")
    if isinstance(images, list):
        values.extend(images)
    elif isinstance(images, str):
        values.append(images)
    for key in ("image_url", "image_uri", "image_path"):
        if payload.get(key):
            values.append(payload[key])
            break
    attachments = payload.get("attachments")
    if isinstance(attachments, list):
        for item in attachments:
            if isinstance(item, dict):
                declared = str(item.get("type") or item.get("kind") or item.get("mime")).lower()
                if declared in {"image", "img", "photo"} or declared.startswith("image/"):
                    values.append(item)

    refs: list[str] = []
    for value in values:
        if isinstance(value, str):
            ref = value.strip()
        elif isinstance(value, dict):
            ref = next(
                (
                    str(value[key]).strip()
                    for key in ("url", "uri", "path", "image_url", "image_uri", "image_path")
                    if value.get(key)
                ),
                "",
            )
        else:
            ref = ""
        if ref and ref not in refs:
            refs.append(ref)
    return refs
