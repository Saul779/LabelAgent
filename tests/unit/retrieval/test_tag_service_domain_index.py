"""S1/S2 生产 Tag Service 领域索引测试。"""

from __future__ import annotations

import pytest

from label_agent.domain.models.candidate import TagCandidate
from label_agent.retrieval.tag_service_domain_index import TagServiceDomainIndex


class _TagService:
    async def search_tags(self, query: str, domain: str) -> list[TagCandidate]:
        assert query == "PMP\n通过项目管理认证"
        assert domain == "certificate"
        common = {
            "domain": domain,
            "dictionary_snapshot_version": "certificate-2026-09-15",
            "vector_state": "READY",
        }
        return [
            TagCandidate(
                **common,
                tag_id="certificate-vector",
                canonical_tag_id="certificate-vector",
                display_name="项目管理认证",
                name_type="standard",
                match_source="vector",
                match_score=0.99,
            ),
            TagCandidate(
                **common,
                tag_id="certificate-pmp-alias",
                canonical_tag_id="certificate-pmp",
                display_name="PMP",
                canonical_display_name="PMP项目管理专业人士认证",
                name_type="alias",
                match_source="exact",
                match_score=1.0,
                metadata={"issuer": "PMI"},
            ),
        ]


@pytest.mark.asyncio
async def test_exact_candidate_precedes_higher_scored_vector_candidate() -> None:
    index = TagServiceDomainIndex("certificate", _TagService())  # type: ignore[arg-type]

    hits = await index.top_k("PMP\n通过项目管理认证", k=2)

    assert [hit.item.id for hit in hits] == [
        "certificate-pmp-alias",
        "certificate-vector",
    ]
    assert hits[0].item.display_name == "PMP项目管理专业人士认证"
    assert hits[0].item.metadata == {"issuer": "PMI"}
    assert hits[0].dictionary_snapshot_version == "certificate-2026-09-15"


@pytest.mark.asyncio
async def test_filters_wrong_domain_and_non_ready_candidates() -> None:
    class _MixedTagService:
        async def search_tags(self, query: str, domain: str) -> list[TagCandidate]:
            _ = query, domain
            return [
                TagCandidate(
                    tag_id="pending",
                    canonical_tag_id="pending",
                    display_name="PMP",
                    name_type="standard",
                    domain="certificate",
                    dictionary_snapshot_version="v1",
                    match_source="exact",
                    match_score=1.0,
                    vector_state="PENDING",
                ),
                TagCandidate(
                    tag_id="career",
                    canonical_tag_id="career",
                    display_name="工程师",
                    name_type="standard",
                    domain="career",
                    dictionary_snapshot_version="v1",
                    match_source="exact",
                    match_score=1.0,
                ),
            ]

    index = TagServiceDomainIndex("certificate", _MixedTagService())  # type: ignore[arg-type]

    assert await index.top_k("PMP") == []
