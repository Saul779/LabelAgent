"""视频抽帧：ffmpeg 均匀采样关键帧，供后续 OCR（不做 Vision）。"""

from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from label_agent.core.exceptions import NonRetryableError
from label_agent.domain.models.content import VideoFrameArtifact
from label_agent.perception.media_guard import MediaGuard
from label_agent.perception.media_local import resolve_local_path
from label_agent.utils.hashing import sha256_hex

logger = logging.getLogger(__name__)

_SAMPLER_VERSION = "ffmpeg-v1"


@dataclass(frozen=True)
class SampledFrame:
    """单帧采样结果：契约产物 + 本地帧路径（供 OCR）。"""

    artifact: VideoFrameArtifact
    path: Path


class VideoFrameSampler:
    """视频抽帧器：按最大时长/最大帧数限制从视频中均匀采样。"""

    def __init__(self, max_duration_sec: int = 120, max_frames: int = 16) -> None:
        """初始化抽帧上限（实现级默认，非 Feature Flag）。"""
        self._max_duration_sec = max_duration_sec
        self._max_frames = max_frames

    @property
    def version(self) -> str:
        """抽帧器版本号。"""
        return _SAMPLER_VERSION

    async def sample(
        self,
        video_uri: str,
        *,
        media_guard: MediaGuard | None = None,
    ) -> list[SampledFrame]:
        """从视频 URI 采样帧；在线程池执行 ffmpeg，避免阻塞事件循环。"""
        return await asyncio.to_thread(self._sample_sync, video_uri, media_guard)

    def _sample_sync(self, video_uri: str, media_guard: MediaGuard | None) -> list[SampledFrame]:
        """同步抽帧实现。"""
        if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
            raise NonRetryableError("系统未安装 ffmpeg/ffprobe，无法抽帧")

        local_path, is_temp = resolve_local_path(
            video_uri, media_guard=media_guard, suffix=Path(video_uri).suffix or ".mp4"
        )
        work_dir = Path(tempfile.mkdtemp(prefix="label_agent_frames_"))
        try:
            duration = _probe_duration_sec(local_path)
            effective = min(duration, float(self._max_duration_sec))
            if effective <= 0:
                raise NonRetryableError(f"视频时长无效: {video_uri}")

            frame_count = max(1, min(self._max_frames, int(effective) + 1))
            # 均匀取点：在 [0, effective) 内取 frame_count 个时间戳
            timestamps = [
                (effective * i) / frame_count if frame_count > 1 else 0.0
                for i in range(frame_count)
            ]
            # 避免最后一帧贴到文件尾导致解码失败
            timestamps = [min(ts, max(effective - 0.05, 0.0)) for ts in timestamps]

            asset_id = sha256_hex(local_path.read_bytes()[: 1024 * 64])[:24]
            frames: list[SampledFrame] = []
            for index, ts in enumerate(timestamps):
                frame_path = work_dir / f"frame_{index:04d}.jpg"
                _extract_frame(local_path, ts, frame_path)
                start_ms = int(ts * 1000)
                # 帧区间用相邻间隔近似；最后一帧到 effective
                if index + 1 < len(timestamps):
                    end_ms = int(timestamps[index + 1] * 1000)
                else:
                    end_ms = int(effective * 1000)
                artifact = VideoFrameArtifact(
                    asset_id=asset_id,
                    frame_id=f"frame_{index:04d}",
                    start_ms=start_ms,
                    end_ms=max(end_ms, start_ms),
                    uri=str(frame_path),
                )
                frames.append(SampledFrame(artifact=artifact, path=frame_path))

            logger.info(
                "抽帧完成 uri=%s frames=%s duration=%.2fs",
                video_uri,
                len(frames),
                effective,
            )
            return frames
        finally:
            if is_temp:
                local_path.unlink(missing_ok=True)


def _probe_duration_sec(path: Path) -> float:
    """用 ffprobe 读取视频时长（秒）。"""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True).strip()
        return float(out)
    except (subprocess.CalledProcessError, ValueError) as exc:
        raise NonRetryableError(f"ffprobe 读取时长失败: {path}") from exc


def _extract_frame(video_path: Path, timestamp_sec: float, output_path: Path) -> None:
    """用 ffmpeg 在指定时间戳截取一帧 JPEG。"""
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{timestamp_sec:.3f}",
        "-i",
        str(video_path),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(output_path),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        raise NonRetryableError(
            f"ffmpeg 抽帧失败 t={timestamp_sec:.3f}: {exc.stderr[-500:] if exc.stderr else exc}"
        ) from exc
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise NonRetryableError(f"抽帧产物为空: {output_path}")
