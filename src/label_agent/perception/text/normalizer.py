"""文本归一化：去除控制字符、统一编码、生成 content_hash 输入。"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from label_agent.utils.hashing import sha256_hex

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_DEFAULT_MAX_CHARS = 20_000


@dataclass(frozen=True)
class NormalizedText:
    """归一化结果：归一化后的文本、其 content_hash，以及是否发生过截断。"""

    text: str
    content_hash: str
    truncated: bool = False


class TextNormalizer:
    """文本归一化器：统一编码、清理噪声字符并按上限截断，为生成 content_hash 提供稳定输入。"""

    def __init__(self, max_chars: int = _DEFAULT_MAX_CHARS) -> None:
        """初始化文本规整器（空白折叠、截断等策略）。"""
        self._max_chars = max_chars

    def normalize(self, raw_text: str) -> NormalizedText:
        """对原始文本做 NFKC 归一化、换行符统一、控制字符与多余空白清理，
        超长时按 max_chars 截断，并计算归一化后文本的 content_hash。
        """
        text = unicodedata.normalize("NFKC", raw_text or "")
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        text = _CONTROL_CHARS.sub("", text)
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = text.strip()

        truncated = False
        if len(text) > self._max_chars:
            text = text[: self._max_chars]
            truncated = True

        return NormalizedText(text=text, content_hash=sha256_hex(text), truncated=truncated)
