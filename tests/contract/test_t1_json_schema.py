"""TaskDetailResult 必须满足 T1 1.0 JSON Schema。"""

from __future__ import annotations

import json
from pathlib import Path

import jsonschema

from label_agent.domain.models.t1_result import TaskDetailResult


def test_t1_result_conforms_to_json_schema() -> None:
    schema_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "label_agent"
        / "validation"
        / "schema"
        / "t1_schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    result = TaskDetailResult(
        accept_mode="specified",
        biz_task_type="relationship",
        relation_target="person",
        relation_target_detail="会修电脑的师傅",
    )

    jsonschema.validate(result.model_dump(mode="json"), schema=schema)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["schema_version"]["const"] == "1.0"
