"""Reciprocal Rank Fusion：融合多路召回结果，按 canonical_tag_id 去重排序。"""

from __future__ import annotations

from label_agent.domain.models.candidate import TagCandidate

_K = 60  # RRF 平滑常数，可按需移入配置


def reciprocal_rank_fusion(result_lists: list[list[TagCandidate]]) -> list[TagCandidate]:
    """对多路召回结果做 RRF，并按 canonical_tag_id 归并同义标签。"""
    scores: dict[str, float] = {}
    by_id: dict[str, TagCandidate] = {}
    for results in result_lists:
        for rank, candidate in enumerate(results, start=1):
            canonical_id = candidate.canonical_tag_id
            scores[canonical_id] = scores.get(canonical_id, 0.0) + 1.0 / (_K + rank)
            current = by_id.get(canonical_id)
            if current is None or candidate.match_score > current.match_score:
                by_id[canonical_id] = candidate
    ordered_ids = sorted(scores, key=lambda canonical_id: scores[canonical_id], reverse=True)
    return [by_id[canonical_id] for canonical_id in ordered_ids]
