"""同一 canonical_tag_id 簇只保留 model_score 最高的一条（Q015 已确认）。"""

from __future__ import annotations

from label_agent.domain.models.proposal import ProposedTag
from label_agent.resolution.dedup import dedup_by_canonical_tag


def test_keeps_highest_score_within_same_cluster() -> None:
    proposed = [
        ProposedTag(tag_id="tag-alias-1", model_score=0.7),
        ProposedTag(tag_id="tag-standard-1", model_score=0.9),
        ProposedTag(tag_id="tag-other", model_score=0.5),
    ]
    canonical_of = {
        "tag-alias-1": "cluster-1",
        "tag-standard-1": "cluster-1",
        "tag-other": "cluster-2",
    }

    deduped = dedup_by_canonical_tag(proposed, canonical_of)

    assert len(deduped) == 2
    kept_ids = {tag.tag_id for tag in deduped}
    assert kept_ids == {"tag-standard-1", "tag-other"}
