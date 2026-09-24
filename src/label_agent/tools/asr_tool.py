"""ASR Tool：只读包装 perception.asr.AsrTranscriber。"""

from __future__ import annotations

from label_agent.perception.asr.transcriber import AsrTranscriber


class AsrTool:
    """ASR 工具封装，供模型/管线按需调用。"""

    name = "asr_transcribe"
    description = "对指定音频/视频资源执行语音转写，返回带时间戳的文本片段"
    parameters_schema = {
        "type": "object",
        "properties": {"audio_uri": {"type": "string"}},
        "required": ["audio_uri"],
    }

    def __init__(self, asr_transcriber: AsrTranscriber) -> None:
        """注入 ASR 转写实现。"""
        self._asr_transcriber = asr_transcriber

    async def invoke(self, audio_uri: str) -> list[dict]:
        """执行一次 ASR 转写。"""
        outcome = await self._asr_transcriber.transcribe(audio_uri)
        return [segment.model_dump() for segment in outcome.segments]
