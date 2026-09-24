"""S3 ContentBundleBuilder / InputRouter(video) 单元测试（引擎用 Fake，不依赖 Paddle/Whisper）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.content import AsrSegment, OcrSegment, VideoFrameArtifact
from label_agent.inference.providers.base import ModelCompletionResult
from label_agent.perception.asr.transcriber import AsrOutcome
from label_agent.perception.content_bundle_builder import ContentBundleBuilder
from label_agent.perception.extractors.base import AttachmentKind
from label_agent.perception.extractors.image_vision_extractor import ImageVisionExtractor
from label_agent.perception.image.ocr import OcrEngine
from label_agent.perception.input_router import InputRouter
from label_agent.perception.text.normalizer import TextNormalizer
from label_agent.perception.video.frame_sampler import SampledFrame, VideoFrameSampler


class _FakeGateway:
    async def complete(self, request, model_alias=None):
        _ = model_alias
        return ModelCompletionResult(
            raw_text="视觉描述：商品海报含运动鞋字样",
            model_name="fake",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
        )


class _FakePromptManager:
    def render(self, scene: str, prompt_version: str, variables: dict) -> tuple[str, str]:
        _ = scene, prompt_version
        return "S3 图片理解助手", f"hint={variables.get('context_hint')}"


class _FakeOcr(OcrEngine):
    def __init__(self) -> None:
        pass

    @property
    def version(self) -> str:
        return "fake-ocr"

    async def recognize(self, image_uri: str, *, asset_id: str = "") -> list[OcrSegment]:
        return [OcrSegment(asset_id=asset_id or "f", text="帧文字:限时折扣", bbox=[0, 0, 1, 1])]


class _FakeSampler(VideoFrameSampler):
    def __init__(self, tmp_path: Path) -> None:
        super().__init__(max_duration_sec=10, max_frames=2)
        self._tmp = tmp_path

    @property
    def version(self) -> str:
        return "fake-sampler"

    async def sample(self, video_uri: str, *, media_guard=None) -> list[SampledFrame]:
        _ = video_uri, media_guard
        frame_path = self._tmp / "frame_0000.jpg"
        frame_path.write_bytes(b"fake-jpeg")
        artifact = VideoFrameArtifact(
            asset_id="vid1",
            frame_id="frame_0000",
            start_ms=0,
            end_ms=1000,
            uri=str(frame_path),
        )
        return [SampledFrame(artifact=artifact, path=frame_path)]


class _FakeAsr:
    version = "fake-asr"

    def __init__(self, *, skipped_no_audio: bool = False, text: str = "语音:包邮") -> None:
        self._skipped = skipped_no_audio
        self._text = text

    async def transcribe(self, video_uri: str, *, asset_id: str = "video", media_guard=None):
        _ = video_uri, media_guard
        if self._skipped:
            return AsrOutcome(skipped_no_audio=True)
        return AsrOutcome(
            segments=[AsrSegment(asset_id=asset_id, start_ms=0, end_ms=500, text=self._text)]
        )


def _ctx(payload: dict) -> JobContext:
    return JobContext(job_id="j", task_id="t", scene="S3", biz_id="biz", payload=payload)


def _builder(
    tmp_path: Path,
    *,
    asr: _FakeAsr | None = None,
) -> ContentBundleBuilder:
    vision = ImageVisionExtractor(
        llm_gateway=_FakeGateway(),  # type: ignore[arg-type]
        prompt_manager=_FakePromptManager(),  # type: ignore[arg-type]
        media_guard=None,
        vision_prompt_version="s3-vision-v1",
        scene="s3",
    )
    return ContentBundleBuilder(
        media_guard=None,
        text_normalizer=TextNormalizer(),
        ocr_engine=_FakeOcr(),
        frame_sampler=_FakeSampler(tmp_path),
        asr_transcriber=asr or _FakeAsr(),  # type: ignore[arg-type]
        image_vision=vision,
    )


def test_input_router_video_fields() -> None:
    router = InputRouter()
    refs = router.route(
        {
            "text": "商品文案",
            "video_path": "D:/data/demo.mp4",
            "attachments": [{"type": "video", "path": "/tmp/a.mov"}],
        }
    )
    kinds = [r.kind for r in refs]
    assert AttachmentKind.TEXT in kinds
    assert kinds.count(AttachmentKind.VIDEO) >= 1
    assert router.version == "v2"


@pytest.mark.asyncio
async def test_builder_text_and_image_vision(tmp_path: Path) -> None:
    img = tmp_path / "poster.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 32)
    bundle = await _builder(tmp_path).build(_ctx({"text": "春季新款", "image_path": str(img)}))
    assert "春季新款" in bundle.normalized_text
    assert "视觉描述" in bundle.normalized_text
    assert "image" in bundle.successful_modalities
    assert "text" in bundle.successful_modalities
    assert bundle.ocr_segments == []


@pytest.mark.asyncio
async def test_builder_video_ocr_and_asr(tmp_path: Path) -> None:
    bundle = await _builder(tmp_path).build(_ctx({"video_path": str(tmp_path / "x.mp4")}))
    assert "帧文字" in bundle.normalized_text
    assert "语音" in bundle.normalized_text
    assert "video_ocr" in bundle.successful_modalities
    assert "asr" in bundle.successful_modalities
    assert len(bundle.video_frame_artifacts) == 1
    assert len(bundle.ocr_segments) == 1
    assert len(bundle.asr_segments) == 1


@pytest.mark.asyncio
async def test_builder_video_skip_asr_without_audio(tmp_path: Path) -> None:
    bundle = await _builder(tmp_path, asr=_FakeAsr(skipped_no_audio=True)).build(
        _ctx({"video_path": str(tmp_path / "silent.mp4")})
    )
    assert "帧文字" in bundle.normalized_text
    assert "asr" not in bundle.successful_modalities
    assert bundle.perception_versions.get("asr_status") == "skipped_no_audio"
    assert "asr" not in bundle.failed_modalities


@pytest.mark.asyncio
async def test_builder_empty_input_raises(tmp_path: Path) -> None:
    with pytest.raises(NonRetryableError, match="缺少可识别附件"):
        await _builder(tmp_path).build(_ctx({}))
