"""S4 ProductLabelResult JSON Schema 导出入口。"""

from __future__ import annotations

from typing import Any

from label_agent.domain.models.s4_result import ProductLabelResult


def load_s4_json_schema() -> dict[str, Any]:
    """由唯一 Pydantic 契约生成 JSON Schema，避免手写 Schema 与代码漂移。"""
    return ProductLabelResult.model_json_schema()
