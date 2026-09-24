"""S3 场景专属 Schema 校验入口。

复用 ``domain.models.s3_result``，此处只负责 JSON Schema 加载。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "validation" / "schema" / "s3_schema.json"


def load_s3_json_schema() -> dict[str, Any]:
    """加载 S3 出参 JSON Schema，供校验使用。"""
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
