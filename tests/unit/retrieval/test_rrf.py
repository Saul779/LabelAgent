"""RRF 融合应按融合分数排序去重（§5.1.3）。"""

from __future__ import annotations

from label_agent.domain.models.candidate import TagCandidate
from label_agent.retrieval.fusion.rrf import reciprocal_rank_fusion


def _candidate(tag_id: str) -> TagCandidate:
    return TagCandidate(
        tag_id=tag_id,
        canonical_tag_id=tag_id,
        display_name=tag_id,
        name_type="standard",
        domain="content",
        dictionary_snapshot_version="dict-1",
        match_source="exact",
        match_score=1.0,
    )


def test_candidate_appearing_in_multiple_lists_ranks_higher() -> None:
    list_a = [_candidate("tag-1"), _candidate("tag-2")]
    list_b = [_candidate("tag-2"), _candidate("tag-1")]
    list_c = [_candidate("tag-3")]

    fused = reciprocal_rank_fusion([list_a, list_b, list_c])

    assert [c.tag_id for c in fused[:2]] == ["tag-1", "tag-2"] or [c.tag_id for c in fused[:2]] == [
        "tag-2",
        "tag-1",
    ]
    assert fused[-1].tag_id == "tag-3"
