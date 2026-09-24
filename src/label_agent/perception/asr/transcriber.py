"""ASR 转写：从视频音轨转写文本；无音轨则跳过（不视为失败）。"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.content import AsrSegment
from label_agent.perception.media_guard import MediaGuard
from label_agent.perception.media_local import resolve_local_path

logger = logging.getLogger(__name__)

_TRANSCRIBER_VERSION = "faster-whisper-v1"


@dataclass(frozen=True)
class AsrOutcome:
    """ASR 结果：片段列表；无音轨时 skipped_no_audio=True 且 segments 为空。"""

    segments: list[AsrSegment] = field(default_factory=list)
    skipped_no_audio: bool = False


class AsrTranscriber:
    """基于 faster-whisper 的视频/音频转写器。"""

    def __init__(self, *, model_size: str = "base", device: str = "cpu") -> None:
        """初始化模型规格；模型惰性加载。"""
        self._model_size = model_size
        self._device = device
        self._model: Any | None = None

    @property
    def version(self) -> str:
        """转写器版本号。"""
        return _TRANSCRIBER_VERSION

    def _ensure_model(self) -> Any:
        """惰性加载 faster-whisper 模型。"""
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "未安装 faster-whisper，请执行: pip install -r requirements-perception.txt"
            ) from exc
        self._model = WhisperModel(self._model_size, device=self._device)
        return self._model

    async def transcribe(
        self,
        video_uri: str,
        *,
        asset_id: str = "video",
        media_guard: MediaGuard | None = None,
    ) -> AsrOutcome:
        """对视频执行 ASR；无音轨返回 skipped_no_audio，不抛错。"""
        return await asyncio.to_thread(self._transcribe_sync, video_uri, asset_id, media_guard)

    def _transcribe_sync(
        self,
        video_uri: str,
        asset_id: str,
        media_guard: MediaGuard | None,
    ) -> AsrOutcome:
        """同步 ASR：探测音轨 → 抽 wav → whisper 转写。"""
        if shutil.which("ffprobe") is None or shutil.which("ffmpeg") is None:
            raise NonRetryableError("系统未安装 ffmpeg/ffprobe，无法 ASR")

        local_path, is_temp = resolve_local_path(
            video_uri, media_guard=media_guard, suffix=Path(video_uri).suffix or ".mp4"
        )
        wav_path: Path | None = None
        try:
            if not _has_audio_stream(local_path):
                logger.info("视频无音轨，跳过 ASR uri=%s", video_uri)
                return AsrOutcome(skipped_no_audio=True)

            wav_path = Path(tempfile.mkstemp(prefix="label_agent_asr_", suffix=".wav")[1])
            _extract_wav(local_path, wav_path)
            model = self._ensure_model()
            segments_iter, _info = model.transcribe(str(wav_path), language="zh")
            segments: list[AsrSegment] = []
            for item in segments_iter:
                text = (item.text or "").strip()
                if not text:
                    continue
                segments.append(
                    AsrSegment(
                        asset_id=asset_id,
                        start_ms=int(item.start * 1000),
                        end_ms=int(item.end * 1000),
                        text=text,
                    )
                )
            logger.info("ASR 完成 uri=%s segments=%s", video_uri, len(segments))
            return AsrOutcome(segments=segments)
        finally:
            if wav_path is not None:
                wav_path.unlink(missing_ok=True)
            if is_temp:
                local_path.unlink(missing_ok=True)


def _has_audio_stream(path: Path) -> bool:
    """ffprobe 检测是否存在音频流。"""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
    except subprocess.CalledProcessError:
        return False
    return bool(out)


def _extract_wav(video_path: Path, wav_path: Path) -> None:
    """用 ffmpeg 抽取单声道 16k wav，供 whisper 使用。"""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(wav_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise NonRetryableError(
            f"抽取音轨失败: {exc.stderr[-500:] if exc.stderr else exc}"
        ) from exc
