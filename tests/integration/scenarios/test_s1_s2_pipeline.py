"""S1/S2 schema 2.0 管线集成测试（mock LLM / vector index）。"""

from __future__ import annotations

import json

import pytest

from label_agent.core.context import JobContext
from label_agent.domain.models.content import ContentBundle
from label_agent.inference.generative_proposer import GenerativeProposer
from label_agent.inference.providers.base import ModelCompletionResult
from label_agent.resolution.evidence_candidate_matcher import EvidenceCandidateMatcher
from label_agent.retrieval.generative_domain_index import DictionaryItem, DomainSearchHit
from label_agent.scenarios.s1_career.pipeline import S1Pipeline
from label_agent.scenarios.s2_skill.pipeline import S2Pipeline
from label_agent.validation.safety.injection_detector import InjectionDetector
from label_agent.validation.safety.pii_detector import PiiDetector


class _StaticLoader:
    async def build(self, ctx: JobContext) -> ContentBundle:
        return ContentBundle(normalized_text=str(ctx.payload.get("text") or ""))


class _PromptManager:
    def render(self, scene: str, prompt_version: str, variables: dict) -> tuple[str, str]:
        return prompt_version, json.dumps(variables, ensure_ascii=False)


class _ScriptedGateway:
    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses

    async def complete(self, request, model_alias=None):
        _ = model_alias
        response_key = request.system_prompt.splitlines()[0]
        raw = self._responses[response_key]
        if "-match-v" in request.system_prompt:
            variables = json.loads(request.user_prompt)
            evidence = json.loads(variables["evidence_json"])
            keyed = f"{request.system_prompt}:{evidence['id']}"
            raw = self._responses[keyed]
        return ModelCompletionResult(
            raw_text=raw,
            model_name="fake",
            prompt_tokens=1,
            completion_tokens=1,
            latency_ms=1,
        )


class _FakeIndex:
    def __init__(self, hits_by_term: dict[str, list[DomainSearchHit]]) -> None:
        self._hits_by_term = hits_by_term

    async def top_k(self, query_text: str, k: int = 5) -> list[DomainSearchHit]:
        for term, hits in self._hits_by_term.items():
            if term in query_text:
                return hits[:k]
        return []

    def find_exact(self, text: str) -> list[DomainSearchHit]:
        return []


def _hit(
    entity_id: str,
    name: str,
    *,
    canonical_id: str | None = None,
    matched_text: str | None = None,
    dictionary_snapshot_version: str = "",
) -> DomainSearchHit:
    return DomainSearchHit(
        item=DictionaryItem(
            id=entity_id,
            display_name=name,
            canonical_id=canonical_id,
        ),
        score=0.9,
        matched_text=matched_text or name,
        dictionary_snapshot_version=dictionary_snapshot_version,
    )


def _ctx(scene: str, text: str) -> JobContext:
    return JobContext(
        job_id="j",
        task_id="t",
        scene=scene,
        biz_id=f"biz-{scene.lower()}",
        payload={"text": text},
    )


@pytest.mark.asyncio
async def test_s1_deduplicates_by_canonical_id_and_sets_public_audit() -> None:
    generated = {
        "occupation_evidence": [
            {"id": "x", "title": "Python工程师", "description": "担任Python工程师"},
            {"id": "y", "title": "后端工程师", "description": "从事后端开发"},
            {"id": "z", "title": "未知职业", "description": "负责未知业务"},
        ],
        "enterprises": [
            {"name": "甲公司", "evidence_ids": ["x"]},
            {"name": "乙公司", "evidence_ids": ["y"]},
        ],
    }
    gateway = _ScriptedGateway(
        {
            "s1-v2": json.dumps(generated, ensure_ascii=False),
            "s1-match-v2": "",
            "s1-match-v2:E001": json.dumps({"occupation_id": "career-001", "confidence": 0.92}),
            "s1-match-v2:E002": json.dumps({"occupation_id": "career-alias", "confidence": 0.80}),
        }
    )
    index = _FakeIndex(
        {
            "Python": [_hit("career-001", "Python工程师", canonical_id="career-canon")],
            "后端": [
                _hit(
                    "career-alias",
                    "软件工程师",
                    canonical_id="career-canon",
                    matched_text="后端工程师",
                )
            ],
        }
    )
    prompts = _PromptManager()
    pipeline = S1Pipeline(
        content_loader=_StaticLoader(),  # type: ignore[arg-type]
        generative_proposer=GenerativeProposer(gateway, prompts),  # type: ignore[arg-type]
        matcher=EvidenceCandidateMatcher(
            domain="career",
            index=index,  # type: ignore[arg-type]
            llm_gateway=gateway,  # type: ignore[arg-type]
            prompt_manager=prompts,  # type: ignore[arg-type]
            prompt_version="s1-match-v2",
        ),
        pii_detector=PiiDetector(),
        injection_detector=InjectionDetector(),
        dictionary_snapshot_version="career-dict",
    )
    result = await pipeline.run(
        _ctx("S1", "担任Python工程师，从事后端开发，负责未知业务，任职甲公司和乙公司")
    )

    assert result.model_dump() == {
        "occupations": [
            {
                "occupation_id": "career-canon",
                "occupation_name": "Python工程师",
                "evidences": [
                    {"evidence_id": "E001", "confidence": 0.92, "reason": ""},
                    {"evidence_id": "E002", "confidence": 0.8, "reason": ""},
                ],
            }
        ],
        "unmatched": [
            {
                "evidence_id": "E003",
                "match_status": "no_match",
                "confidence": 0.0,
                "reason": "标准词典未召回候选",
            },
        ],
        "evidence": [
            {"evidence_id": "E001", "title": "Python工程师", "description": "担任Python工程师"},
            {"evidence_id": "E002", "title": "后端工程师", "description": "从事后端开发"},
            {"evidence_id": "E003", "title": "未知职业", "description": "负责未知业务"},
        ],
        "enterprises": ["甲公司", "乙公司"],
        "audit": 1,
    }
    assert result.audit == 1
    assert not hasattr(result, "skill_tags")


@pytest.mark.asyncio
async def test_s2_illegal_model_id_keeps_evidence_without_triggering_audit() -> None:
    gateway = _ScriptedGateway(
        {
            "s2-v3": json.dumps(
                {
                    "certificate_evidence": [
                        {"title": "PMP", "description": "通过PMP认证"},
                        {"title": "AWS SAA", "description": "通过AWS SAA认证"},
                    ]
                },
                ensure_ascii=False,
            ),
            "s2-match-v3": "",
            "s2-match-v3:E001": json.dumps(
                {"certificate_id": "certificate-001", "confidence": 0.9}
            ),
            "s2-match-v3:E002": json.dumps({"certificate_id": "outside-top5", "confidence": 0.9}),
        }
    )
    index = _FakeIndex(
        {
            "PMP": [
                _hit(
                    "certificate-001",
                    "PMP项目管理专业人士认证",
                    dictionary_snapshot_version="certificate-production-v1",
                )
            ],
            "AWS": [_hit("certificate-003", "AWS认证解决方案架构师-助理级")],
        }
    )
    prompts = _PromptManager()
    pipeline = S2Pipeline(
        content_loader=_StaticLoader(),  # type: ignore[arg-type]
        generative_proposer=GenerativeProposer(gateway, prompts),  # type: ignore[arg-type]
        matcher=EvidenceCandidateMatcher(
            domain="certificate",
            index=index,  # type: ignore[arg-type]
            llm_gateway=gateway,  # type: ignore[arg-type]
            prompt_manager=prompts,  # type: ignore[arg-type]
            prompt_version="s2-match-v3",
        ),
        pii_detector=PiiDetector(),
        injection_detector=InjectionDetector(),
    )
    result = await pipeline.run(_ctx("S2", "通过PMP认证，并通过AWS SAA认证"))

    assert result.certificates[0].certificate_id == "certificate-001"
    assert result.certificates[0].certificate_name == "PMP项目管理专业人士认证"
    assert result.certificates[0].evidences[0].evidence_id == "E001"
    assert [item.evidence_id for item in result.evidence] == ["E001", "E002"]
    assert result.dictionary_snapshot_version == "certificate-production-v1"
    assert result.audit == 0


@pytest.mark.asyncio
async def test_s1_accepts_explicit_no_match_without_forced_selection() -> None:
    gateway = _ScriptedGateway(
        {
            "s1-v2": json.dumps(
                {
                    "occupation_evidence": [{"title": "神秘职业", "description": "担任神秘职业"}],
                    "enterprises": [],
                },
                ensure_ascii=False,
            ),
            "s1-match-v2": "",
            "s1-match-v2:E001": json.dumps(
                {"match_status": "no_match", "confidence": 0.2, "reason": "候选均不相符"},
                ensure_ascii=False,
            ),
        }
    )
    prompts = _PromptManager()
    pipeline = S1Pipeline(
        content_loader=_StaticLoader(),  # type: ignore[arg-type]
        generative_proposer=GenerativeProposer(gateway, prompts),  # type: ignore[arg-type]
        matcher=EvidenceCandidateMatcher(
            domain="career",
            index=_FakeIndex({"神秘": [_hit("career-001", "软件工程师")]}),  # type: ignore[arg-type]
            llm_gateway=gateway,  # type: ignore[arg-type]
            prompt_manager=prompts,  # type: ignore[arg-type]
            prompt_version="s1-match-v2",
        ),
        pii_detector=PiiDetector(),
        injection_detector=InjectionDetector(),
    )

    result = await pipeline.run(_ctx("S1", "担任神秘职业"))

    assert result.occupations == []
    assert result.unmatched[0].match_status == "no_match"
    assert result.audit == 1


@pytest.mark.asyncio
async def test_s2_accepts_ambiguous_without_certificate_selection() -> None:
    gateway = _ScriptedGateway(
        {
            "s2-v3": json.dumps(
                {
                    "certificate_evidence": [
                        {"title": "AWS 架构师认证", "description": "获得AWS架构师认证"}
                    ]
                },
                ensure_ascii=False,
            ),
            "s2-match-v3": "",
            "s2-match-v3:E001": json.dumps(
                {"match_status": "ambiguous", "confidence": 0.72, "reason": "级别不明确"},
                ensure_ascii=False,
            ),
        }
    )
    prompts = _PromptManager()
    pipeline = S2Pipeline(
        content_loader=_StaticLoader(),  # type: ignore[arg-type]
        generative_proposer=GenerativeProposer(gateway, prompts),  # type: ignore[arg-type]
        matcher=EvidenceCandidateMatcher(
            domain="certificate",
            index=_FakeIndex(
                {
                    "AWS": [
                        _hit("certificate-associate", "AWS架构师助理级"),
                        _hit("certificate-professional", "AWS架构师专业级"),
                    ]
                }
            ),  # type: ignore[arg-type]
            llm_gateway=gateway,  # type: ignore[arg-type]
            prompt_manager=prompts,  # type: ignore[arg-type]
            prompt_version="s2-match-v3",
        ),
        pii_detector=PiiDetector(),
        injection_detector=InjectionDetector(),
    )

    result = await pipeline.run(_ctx("S2", "获得AWS架构师认证"))

    assert result.certificates == []
    assert result.unmatched[0].match_status == "ambiguous"
    assert [item.evidence_id for item in result.evidence] == ["E001"]
    assert result.audit == 1


@pytest.mark.asyncio
async def test_generation_parse_failure_returns_empty_result_with_audit_zero() -> None:
    gateway = _ScriptedGateway({"s1-v2": "not-json"})
    prompts = _PromptManager()
    pipeline = S1Pipeline(
        content_loader=_StaticLoader(),  # type: ignore[arg-type]
        generative_proposer=GenerativeProposer(gateway, prompts),  # type: ignore[arg-type]
        matcher=EvidenceCandidateMatcher(
            domain="career",
            index=_FakeIndex({}),  # type: ignore[arg-type]
            llm_gateway=gateway,  # type: ignore[arg-type]
            prompt_manager=prompts,  # type: ignore[arg-type]
            prompt_version="s1-match-v2",
        ),
        pii_detector=PiiDetector(),
        injection_detector=InjectionDetector(),
    )
    result = await pipeline.run(_ctx("S1", "无法解析"))
    assert result.occupations == []
    assert result.evidence == []
    assert result.audit == 0
