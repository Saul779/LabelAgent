"""注入检测（§6.2 第 3 条）：新建标签名称不得包含疑似 Prompt 注入/脚本片段。"""

from __future__ import annotations

from label_agent.core.exceptions import SafetyGateRejectedError

_SUSPICIOUS_TOKENS = ("ignore previous", "system:", "<script", "```")


class InjectionDetector:
    """业务文本注入检测：防止候选名等字段携带提示注入。"""

    def assert_clean(self, text: str) -> None:
        """文本命中注入模式则抛出安全门禁异常。"""
        lowered = text.lower()
        for token in _SUSPICIOUS_TOKENS:
            if token in lowered:
                raise SafetyGateRejectedError(f"命中疑似注入片段: {token}")
