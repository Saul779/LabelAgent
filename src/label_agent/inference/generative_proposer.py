"""GenerativeProposer：S1/S2 生成式提议器（不受候选库约束）。

只产出 GeneratedCandidate，不产生最终 ID、不执行写操作、不决定阈值。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from label_agent.core.context import JobContext
from label_agent.core.exceptions import NeedReviewError
from label_agent.domain.models.certificate_evidence import (
    CertificateEvidence,
    EnterpriseEvidence,
    GeneratedEvidenceBatch,
)
from label_agent.domain.models.generative_candidate import GeneratedCandidate
from label_agent.inference.llm_gateway import LlmGateway
from label_agent.inference.prompts.prompt_manager import PromptManager
from label_agent.inference.providers.base import ModelCompletionRequest

logger = logging.getLogger(__name__)

_MAX_CANDIDATES = 5
_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)


class GenerativeProposer:
    """S1/S2 生成式提议器：不受候选库约束，只产出 GeneratedCandidate，不写库、不定阈值。"""

    def __init__(self, llm_gateway: LlmGateway, prompt_manager: PromptManager) -> None:
        """注入 LLM 网关与 Prompt 管理器。"""
        self._llm_gateway = llm_gateway
        self._prompt_manager = prompt_manager

    async def propose(
        self,
        ctx: JobContext,
        *,
        domain: str,
        prompt_version: str,
        scene: str | None = None,
        extra_variables: dict[str, Any] | None = None,
    ) -> list[GeneratedCandidate]:
        """按 domain/scene 渲染 Prompt，调用 LLM 生成候选列表；解析失败时强制 JSON 重试一次。"""
        scene_key = (scene or ctx.scene).lower()
        normalized_text = ctx.content_bundle.normalized_text if ctx.content_bundle else ""
        variables: dict[str, Any] = {
            "normalized_text": normalized_text,
            "domain": domain,
            "career_hints": "",
        }
        if extra_variables:
            variables.update(extra_variables)

        system_prompt, user_prompt = self._prompt_manager.render(
            scene=scene_key,
            prompt_version=prompt_version,
            variables=variables,
        )
        request = ModelCompletionRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema={"type": "object"},
            temperature=0.0,
            max_tokens=1024,
        )

        result = await self._llm_gateway.complete(request)
        try:
            return self._parse(result.raw_text)
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as first_error:
            logger.warning("生成式提议 JSON 解析失败，重试 1 次: %s", first_error)
            retry_request = ModelCompletionRequest(
                system_prompt=system_prompt
                + "\n上次输出不是合法 JSON，请仅输出符合 Schema 的 JSON 对象。",
                user_prompt=user_prompt,
                response_schema={"type": "object"},
                temperature=0.0,
                max_tokens=1024,
            )
            retry_result = await self._llm_gateway.complete(retry_request)
            try:
                return self._parse(retry_result.raw_text)
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                raise NeedReviewError(f"生成式提议 JSON 解析失败: {exc}") from exc

    async def propose_evidence(
        self,
        ctx: JobContext,
        *,
        domain: str,
        prompt_version: str,
        scene: str,
        evidence_key: str,
        include_enterprises: bool = False,
    ) -> GeneratedEvidenceBatch:
        """生成 0~5 条临时编号证据；S1 可同时提取最多 10 个企业。"""
        normalized_text = ctx.content_bundle.normalized_text if ctx.content_bundle else ""
        system_prompt, user_prompt = self._prompt_manager.render(
            scene=scene.lower(),
            prompt_version=prompt_version,
            variables={"normalized_text": normalized_text, "domain": domain},
        )
        request = ModelCompletionRequest(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_schema={"type": "object"},
            temperature=0.0,
            max_tokens=1536,
        )
        result = await self._llm_gateway.complete(request)
        try:
            return self._parse_evidence(
                result.raw_text,
                evidence_key=evidence_key,
                include_enterprises=include_enterprises,
                source_text=normalized_text,
            )
        except (json.JSONDecodeError, ValueError, KeyError, TypeError) as first_error:
            logger.warning("证据生成 JSON 解析失败，重试 1 次: %s", first_error)
            retry_request = ModelCompletionRequest(
                system_prompt=system_prompt
                + "\n上次输出不是合法 JSON，请仅输出符合 Schema 的 JSON 对象。",
                user_prompt=user_prompt,
                response_schema={"type": "object"},
                temperature=0.0,
                max_tokens=1536,
            )
            retry_result = await self._llm_gateway.complete(retry_request)
            try:
                return self._parse_evidence(
                    retry_result.raw_text,
                    evidence_key=evidence_key,
                    include_enterprises=include_enterprises,
                    source_text=normalized_text,
                )
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as exc:
                raise NeedReviewError(f"证据生成 JSON 解析失败: {exc}") from exc

    def _parse_evidence(
        self,
        raw_text: str,
        *,
        evidence_key: str,
        include_enterprises: bool,
        source_text: str,
    ) -> GeneratedEvidenceBatch:
        payload = self._loads_json(raw_text)
        raw_evidence = payload.get(evidence_key)
        if not isinstance(raw_evidence, list):
            raise ValueError(f"缺少 {evidence_key} 数组")

        evidence: list[CertificateEvidence] = []
        raw_id_map: dict[str, str] = {}
        for raw in raw_evidence[:_MAX_CANDIDATES]:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            description = str(raw.get("description") or "").strip()
            if not title or not description:
                continue
            if description not in source_text:
                logger.warning("丢弃非原文摘录的证据 title=%s", title)
                continue
            evidence_id = f"E{len(evidence) + 1:03d}"
            raw_id = str(raw.get("id") or evidence_id).strip()
            raw_id_map[raw_id] = evidence_id
            raw_id_map[evidence_id] = evidence_id
            evidence.append(
                CertificateEvidence(
                    id=evidence_id,
                    title=title,
                    description=description,
                )
            )

        enterprises: list[EnterpriseEvidence] = []
        if include_enterprises:
            by_name: dict[str, EnterpriseEvidence] = {}
            valid_ids = {item.id for item in evidence}
            raw_enterprises = payload.get("enterprises") or []
            if not isinstance(raw_enterprises, list):
                raise ValueError("enterprises 必须为数组")
            for raw in raw_enterprises:
                if not isinstance(raw, dict):
                    continue
                name = str(raw.get("name") or "").strip()
                if not name:
                    continue
                refs = raw.get("evidence_ids") or []
                if not isinstance(refs, list):
                    refs = []
                mapped_refs: list[str] = []
                for ref in refs:
                    mapped = raw_id_map.get(str(ref).strip())
                    if mapped in valid_ids and mapped not in mapped_refs:
                        mapped_refs.append(mapped)
                key = name.casefold()
                if key in by_name:
                    current = by_name[key]
                    current.evidence_ids.extend(
                        ref for ref in mapped_refs if ref not in current.evidence_ids
                    )
                    continue
                if len(by_name) >= 10:
                    continue
                enterprise = EnterpriseEvidence(name=name, evidence_ids=mapped_refs)
                by_name[key] = enterprise
                enterprises.append(enterprise)

        return GeneratedEvidenceBatch(evidence=evidence, enterprises=enterprises)

    def _parse(self, raw_text: str) -> list[GeneratedCandidate]:
        """将模型 JSON 输出解析为 GeneratedCandidate 列表（最多 5 条）。"""
        payload = self._loads_json(raw_text)
        raw_candidates = payload.get("candidates")
        if raw_candidates is None and isinstance(payload.get("items"), list):
            raw_candidates = payload["items"]
        if not isinstance(raw_candidates, list):
            raise ValueError("缺少 candidates 数组")

        parsed: list[GeneratedCandidate] = []
        for item in raw_candidates[:_MAX_CANDIDATES]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("display_name") or "").strip()
            if not name:
                continue
            score = float(item.get("model_score", 0.0))
            score = min(1.0, max(0.0, score))
            structured = item.get("structured_fields") or {}
            if not isinstance(structured, dict):
                structured = {}
            evidence = item.get("evidence_refs") or []
            if not isinstance(evidence, list):
                evidence = []
            parsed.append(
                GeneratedCandidate(
                    display_name=name,
                    model_score=score,
                    structured_fields=structured,
                    evidence_refs=evidence,
                )
            )
        return parsed

    @staticmethod
    def _loads_json(raw_text: str) -> dict[str, Any]:
        """从原始响应中提取 JSON 对象，兼容 markdown code fence。"""
        text = (raw_text or "").strip()
        if not text:
            raise ValueError("空响应")
        match = _JSON_FENCE.search(text)
        if match:
            text = match.group(1).strip()
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("根节点必须为对象")
        return data
