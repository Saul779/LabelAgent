"""时间工具：统一使用毫秒时间戳。"""

from __future__ import annotations

import time


def now_ms() -> int:
    """当前 UTC 毫秒时间戳。"""
    return int(time.time() * 1000)
