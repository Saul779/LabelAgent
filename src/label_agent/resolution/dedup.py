"""按 canonical_tag_id 去重（Q015 已确认，同一簇只占 1 额度）。"""

from __future__ import annotations

from label_agent.domain.models.proposal import ProposedTag


def dedup_by_canonical_tag(
    proposed_tags: list[ProposedTag],
    canonical_of: dict[str, str],
) -> list[ProposedTag]:
    """canonical_of: tag_id -> canonical_tag_id 映射（来自候选召回结果）。

    同一簇只保留 model_score 最高的一条。
    """
    best_by_cluster: dict[str, ProposedTag] = {}
    for tag in proposed_tags:
        if tag.tag_id is None and tag.new_tag_request is None:
            continue
        if tag.tag_id is not None:
            cluster = canonical_of.get(tag.tag_id, tag.tag_id)
        else:
            request = tag.new_tag_request
            assert request is not None
            proposed_name = request.proposed_name.strip().casefold()
            cluster = f"new:{proposed_name}"
        current_best = best_by_cluster.get(cluster)
        if current_best is None or tag.model_score > current_best.model_score:
            best_by_cluster[cluster] = tag
    return sorted(best_by_cluster.values(), key=lambda item: item.model_score, reverse=True)
