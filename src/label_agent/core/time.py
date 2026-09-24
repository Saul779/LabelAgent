"""时间工具：统一使用 UTC 毫秒时间戳，避免各模块各自实现。"""

from __future__ import annotations

import time


def now_ms() -> int:
    """返回当前 Unix 毫秒时间戳，供耗时统计与事件时间戳。"""
    return int(time.time() * 1000)


def elapsed_ms(start_ms: int) -> int:
    """计算自起点以来的耗时（毫秒）。"""
    return now_ms() - start_ms
