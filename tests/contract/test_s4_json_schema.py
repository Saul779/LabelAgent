"""S4 JSON Schema 导出契约测试（不依赖外部 jsonschema 包）。"""

from __future__ import annotations

from label_agent.scenarios.s4_product.schema import load_s4_json_schema


def test_s4_schema_requires_business_decision_and_model_runs() -> None:
    schema = load_s4_json_schema()

    assert schema["additionalProperties"] is False
    assert {"product_id", "taxonomy_version", "decision", "model_runs"}.issubset(schema["required"])
    decision_schema = schema["properties"]["decision"]
    assert decision_schema["enum"] == ["classified", "unknown", "need_review"]
