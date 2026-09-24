"""通用校验器：非业务语义的输入合法性检查。"""

from __future__ import annotations


def is_non_empty_str(value: str | None) -> bool:
    """判断是否为非空字符串。"""
    return isinstance(value, str) and len(value.strip()) > 0
