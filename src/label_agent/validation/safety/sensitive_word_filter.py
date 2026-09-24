"""敏感词/辱骂/广告词检测（§6.2 第 3 条），及 S4 敏感属性拦截（§5.4、§8）。"""

from __future__ import annotations

from label_agent.core.exceptions import SafetyGateRejectedError

_SENSITIVE_ATTRIBUTES = {"health", "religion", "politics", "sexual_orientation"}


class SensitiveWordFilter:
    """敏感词过滤门禁。"""

    def __init__(self, banned_words: set[str]) -> None:
        """加载敏感词表。"""
        self._banned_words = banned_words

    def assert_clean(self, text: str) -> None:
        """内容含敏感词则拒绝。"""
        for word in self._banned_words:
            if word in text:
                raise SafetyGateRejectedError(f"命中敏感词: {word}")


class SensitiveAttributeGuard:
    """S4 强制安全规则：禁止推断健康、宗教、政治、性取向等敏感属性。"""

    def assert_no_sensitive_inference(self, feature_names: list[str]) -> None:
        """检查特征名是否落入禁止推断的敏感属性集合，命中则拒绝。"""
        hit = _SENSITIVE_ATTRIBUTES.intersection(feature_names)
        if hit:
            raise SafetyGateRejectedError(f"命中禁止推断的敏感属性: {hit}")
