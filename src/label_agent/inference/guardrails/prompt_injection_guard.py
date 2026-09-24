"""Prompt 注入防护：业务文本/OCR/ASR 内容不可信，不得改写系统 Prompt（§8）。"""

from __future__ import annotations


class PromptInjectionGuard:
    """LLM 调用前的 Prompt 注入检测护栏。"""

    def __init__(self, banned_patterns: list[str]) -> None:
        """配置禁止出现的注入模式列表。"""
        self._banned_patterns = banned_patterns

    def assert_safe(self, user_prompt: str) -> None:
        """检查用户侧文本是否含注入模式，命中则拒绝。"""
        lowered = user_prompt.lower()
        for pattern in self._banned_patterns:
            if pattern.lower() in lowered:
                raise ValueError(f"检测到可疑注入模式: {pattern}")
