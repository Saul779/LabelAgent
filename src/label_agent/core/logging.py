"""结构化日志（JSON），统一携带 trace_id/job_id/scene 等上下文字段。

安全约束（§8）：日志不得记录完整证件、原文或长期媒体 URL，
调用方必须使用 `redact()` 处理敏感字段后再传入 extra。
"""

from __future__ import annotations

import logging
import time
from typing import Any

import orjson

_REDACT_KEYS = {"id_card", "phone", "raw_text", "media_url", "credential_no"}


def redact(payload: dict[str, Any]) -> dict[str, Any]:
    """对日志字段做脱敏，避免敏感信息落盘。"""
    return {k: ("***" if k in _REDACT_KEYS else v) for k, v in payload.items()}


class JsonFormatter(logging.Formatter):
    """将日志记录格式化为 JSON，便于采集与检索。"""

    def format(self, record: logging.LogRecord) -> str:
        """把 LogRecord 转为 JSON 字符串。"""
        base = {
            "ts": time.time(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        extra = getattr(record, "extra_fields", None)
        if extra:
            base.update(redact(extra))
        if record.exc_info:
            base["exc_info"] = self.formatException(record.exc_info)
        return orjson.dumps(base).decode()


def get_logger(name: str) -> logging.Logger:
    """按模块名获取已配置的 Logger。"""
    return logging.getLogger(name)
