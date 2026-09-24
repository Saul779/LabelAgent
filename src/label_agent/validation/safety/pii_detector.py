"""PII 检测（§6.2 第 3 条）：身份证号、手机号等敏感信息不得进入新建标签名称。"""

from __future__ import annotations

import re

from label_agent.core.exceptions import SafetyGateRejectedError

_PATTERNS = {
    "id_card": re.compile(r"\d{17}[\dXx]"),
    "phone": re.compile(r"1[3-9]\d{9}"),
}


class PiiDetector:
    """PII 检测：避免姓名/证件号等敏感信息进入标签结果。"""

    def assert_clean(self, text: str) -> None:
        """文本命中 PII 模式则抛出安全门禁异常。"""
        for name, pattern in _PATTERNS.items():
            if pattern.search(text):
                raise SafetyGateRejectedError(f"命中 PII 模式: {name}")
