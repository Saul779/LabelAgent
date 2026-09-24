"""OCR Tool：只读包装 perception.image.OcrEngine。"""

from __future__ import annotations

from label_agent.perception.image.ocr import OcrEngine


class OcrTool:
    """OCR 工具封装。"""

    name = "ocr_recognize"
    description = "对指定图片资源执行 OCR，返回文本片段"
    parameters_schema = {
        "type": "object",
        "properties": {"image_uri": {"type": "string"}},
        "required": ["image_uri"],
    }

    def __init__(self, ocr_engine: OcrEngine) -> None:
        """注入 OCR 引擎。"""
        self._ocr_engine = ocr_engine

    async def invoke(self, image_uri: str) -> list[dict]:
        """执行一次 OCR。"""
        segments = await self._ocr_engine.recognize(image_uri, asset_id="")
        return [segment.model_dump() for segment in segments]
