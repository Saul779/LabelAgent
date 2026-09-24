"""ContentLabelResult 必须满足 validation/schema/s3_schema.json。"""

from __future__ import annotations

import jsonschema

from label_agent.domain.models.s3_result import CategoryResult, ContentLabelResult, TagResult
from label_agent.scenarios.s3_content.schema import load_s3_json_schema


def test_content_label_result_conforms_to_json_schema() -> None:
    result = ContentLabelResult(
        biz_id="dynamic-123",
        result_revision=1,
        dictionary_snapshot_version="dict-2026-07-20",
        model_run_id="run-1",
        prompt_version="s3-v3",
        policy_version="provisional-rule-mvp-1",
        primary_category=CategoryResult(category_id="cat-photo", name="摄影", confidence=0.92),
        tags=[
            TagResult(
                tag_id="tag-19",
                canonical_tag_id="tag-19",
                display_name="复古胶片风",
                name_type="standard",
                source="matched",
                model_score=0.86,
                final_confidence=0.84,
                vector_state="READY",
            )
        ],
    )

    schema = load_s3_json_schema()
    jsonschema.validate(instance=result.model_dump(mode="json"), schema=schema)
