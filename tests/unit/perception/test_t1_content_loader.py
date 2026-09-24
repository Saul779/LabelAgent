"""T1 首版仅支持文本+图片，描述与正文优先。"""

from __future__ import annotations

import pytest

from label_agent.core.context import JobContext
from label_agent.perception.extractors.base import ExtractionResult
from label_agent.perception.t1_content_loader import T1ContentLoader, T1InputError
from label_agent.perception.text.normalizer import TextNormalizer


class _UnusedGateway:
    async def complete(self, request, model_alias=None):
        raise AssertionError("本测试不应直接调用网关")


class _PromptManager:
    def render(self, scene: str, prompt_version: str, variables: dict) -> tuple[str, str]:
        return "system", "user"


class _ImageExtractor:
    async def extract(self, attachment, *, context_hint=""):
        _ = attachment
        assert "描述（优先）：需要远程处理" in context_hint
        return ExtractionResult(
            text="图片写着必须到店",
            successful_modality="image",
        )


def _loader() -> T1ContentLoader:
    loader = T1ContentLoader(
        TextNormalizer(),
        None,
        _UnusedGateway(),  # type: ignore[arg-type]
        _PromptManager(),  # type: ignore[arg-type]
    )
    loader._image_extractor = _ImageExtractor()  # type: ignore[assignment]
    return loader


def _ctx(payload: dict) -> JobContext:
    return JobContext(
        job_id="j",
        task_id="t",
        scene="T1",
        biz_id="b",
        payload=payload,
    )


@pytest.mark.asyncio
async def test_description_precedes_conflicting_image_information() -> None:
    bundle = await _loader().build(
        _ctx(
            {
                "description": "需要远程处理",
                "attachments": [{"type": "image", "path": "fake.png"}],
            }
        )
    )

    assert bundle.normalized_text.index("需要远程处理") < bundle.normalized_text.index(
        "图片写着必须到店"
    )
    assert "冲突时以本节为准" in bundle.normalized_text


@pytest.mark.asyncio
async def test_t1_rejects_pdf_in_first_release() -> None:
    with pytest.raises(T1InputError, match="只支持文本和图片"):
        await _loader().build(
            _ctx({"accept_mode": "public", "attachments": [{"type": "pdf", "path": "a.pdf"}]})
        )
