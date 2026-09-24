"""基于 YAML 词表的内存 Tag Service，实现 S3 MVP 的只读召回与可选建标。"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

from label_agent.domain.models.candidate import CategoryCandidate, TagCandidate
from label_agent.domain.models.tag import LifecycleStatus, Tag, VectorState


class FixtureTagServiceClient:
    """从本地 fixture 加载分类和标签，并以内存方式实现 Tag Service 协议。"""

    def __init__(
        self,
        *,
        dictionary_snapshot_version: str,
        domain: str,
        categories: list[CategoryCandidate],
        tag_specs: list[dict[str, Any]],
    ) -> None:
        """保存词表快照、分类候选及原始标签定义，供检索和创建使用。"""
        self.dictionary_snapshot_version = dictionary_snapshot_version
        self.domain = domain
        self._categories = list(categories)
        self._tag_specs = list(tag_specs)
        self._created_tags: dict[str, Tag] = {}

    @classmethod
    def from_yaml(cls, path: Path) -> FixtureTagServiceClient:
        """读取并校验 YAML fixture，构建内存 Tag Service 客户端。"""
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"S3 词表 fixture 顶层必须是对象: {path}")
        snapshot = str(raw.get("dictionary_snapshot_version") or "").strip()
        domain = str(raw.get("domain") or "content").strip()
        if not snapshot:
            raise ValueError(f"S3 词表缺少 dictionary_snapshot_version: {path}")

        categories = [
            CategoryCandidate(
                category_id=str(item["id"]),
                name=str(item["name"]),
                domain=domain,
                dictionary_snapshot_version=snapshot,
                level=int(item.get("level") or 1),
                parent_category_id=item.get("parent_id"),
            )
            for item in raw.get("categories") or []
        ]
        tag_specs = [dict(item) for item in raw.get("tags") or []]
        return cls(
            dictionary_snapshot_version=snapshot,
            domain=domain,
            categories=categories,
            tag_specs=tag_specs,
        )

    async def search_tags(self, query: str, domain: str) -> list[TagCandidate]:
        """按标准名、别名和字符 n-gram 相似度返回多路标签候选。"""
        if domain != self.domain:
            return []
        normalized_query = _normalize(query)
        results: list[TagCandidate] = []
        for item in self._tag_specs:
            results.extend(self._match_tag_spec(item, normalized_query))
        results.extend(self._match_created_tags(normalized_query))
        return sorted(results, key=lambda candidate: candidate.match_score, reverse=True)

    async def search_categories(self, domain: str) -> list[CategoryCandidate]:
        """按领域返回只读分类字典；分类不提供创建能力。"""
        if domain != self.domain:
            return []
        return list(self._categories)

    async def create_tag(
        self,
        proposed_name: str,
        domain: str,
        idempotency_key: str,
    ) -> Tag:
        """按幂等键创建内存标签，重复请求返回同一标签实体。"""
        if domain != self.domain:
            raise ValueError(f"不允许在未知 domain 创建标签: {domain}")
        tag_id = f"tag-created-{hashlib.sha256(idempotency_key.encode('utf-8')).hexdigest()[:16]}"
        existing = self._created_tags.get(tag_id)
        if existing is not None:
            return existing
        tag = Tag(
            tag_id=tag_id,
            canonical_tag_id=tag_id,
            display_name=proposed_name.strip(),
            name_type="standard",
            domain=domain,
            lifecycle_status=LifecycleStatus.ACTIVE,
            vector_state=VectorState.PENDING,
            tag_definition_version=1,
            embedding_space_id="mvp-default",
        )
        self._created_tags[tag_id] = tag
        return tag

    async def get_tag(self, tag_id: str) -> Tag | None:
        """按标签 ID 查询本次进程内创建的标签。"""
        return self._created_tags.get(tag_id)

    async def update_vector_state(
        self,
        tag_id: str,
        vector_state: VectorState,
        *,
        expected_definition_version: int,
    ) -> Tag:
        """带版本保护地更新内存标签向量状态。"""
        tag = self._created_tags[tag_id]
        if tag.tag_definition_version != expected_definition_version:
            raise ValueError("标签定义版本不匹配")
        updated = tag.model_copy(update={"vector_state": vector_state})
        self._created_tags[tag_id] = updated
        return updated

    async def list_tags_by_vector_state(
        self,
        vector_state: VectorState,
        *,
        limit: int,
    ) -> list[Tag]:
        """读取指定向量状态的内存标签。"""
        return [tag for tag in self._created_tags.values() if tag.vector_state == vector_state][
            :limit
        ]

    def _match_tag_spec(
        self,
        item: dict[str, Any],
        normalized_query: str,
    ) -> list[TagCandidate]:
        """对单条 fixture 标签生成 exact、alias、bm25 三路候选。"""
        tag_id = str(item["id"])
        canonical_id = str(item.get("canonical_id") or tag_id)
        display_name = str(item["display_name"])
        aliases = [str(alias) for alias in item.get("aliases") or []]
        common = {
            "tag_id": tag_id,
            "canonical_tag_id": canonical_id,
            "domain": self.domain,
            "dictionary_snapshot_version": self.dictionary_snapshot_version,
            "vector_state": str(item.get("vector_state") or VectorState.READY.value),
        }
        candidates: list[TagCandidate] = []
        normalized_name = _normalize(display_name)
        if normalized_name and normalized_name in normalized_query:
            candidates.append(
                TagCandidate(
                    **common,
                    display_name=display_name,
                    name_type="standard",
                    match_source="exact",
                    match_score=1.0,
                )
            )

        matched_aliases = [alias for alias in aliases if _normalize(alias) in normalized_query]
        if matched_aliases:
            candidates.append(
                TagCandidate(
                    **common,
                    display_name=matched_aliases[0],
                    name_type="alias",
                    match_source="alias",
                    match_score=0.95,
                )
            )

        fuzzy_score = max(
            [_ngram_recall(normalized_query, normalized_name)]
            + [_ngram_recall(normalized_query, _normalize(alias)) for alias in aliases]
        )
        if fuzzy_score >= 0.35:
            candidates.append(
                TagCandidate(
                    **common,
                    display_name=display_name,
                    name_type="standard",
                    match_source="bm25",
                    match_score=round(fuzzy_score, 6),
                )
            )
        return candidates

    def _match_created_tags(self, normalized_query: str) -> list[TagCandidate]:
        """让本进程内创建的标签可被后续精确召回，用于验证幂等收敛。"""
        results: list[TagCandidate] = []
        for tag in self._created_tags.values():
            if _normalize(tag.display_name) not in normalized_query:
                continue
            results.append(
                TagCandidate(
                    tag_id=tag.tag_id,
                    canonical_tag_id=tag.canonical_tag_id,
                    display_name=tag.display_name,
                    name_type=tag.name_type,
                    domain=tag.domain,
                    dictionary_snapshot_version=self.dictionary_snapshot_version,
                    match_source="exact",
                    match_score=1.0,
                    vector_state=tag.vector_state.value,
                )
            )
        return results


def _normalize(text: str) -> str:
    """使用 NFKC、大小写折叠和符号清理生成稳定匹配文本。"""
    normalized = unicodedata.normalize("NFKC", text).casefold()
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", normalized)


def _ngram_recall(query: str, term: str, size: int = 2) -> float:
    """计算词条 n-gram 在查询中的覆盖率，作为 MVP 模糊召回分数。"""
    if not query or not term:
        return 0.0
    if term in query:
        return 1.0
    if len(term) < size:
        return 1.0 if term in query else 0.0
    term_grams = {term[index : index + size] for index in range(len(term) - size + 1)}
    query_grams = {query[index : index + size] for index in range(len(query) - size + 1)}
    return len(term_grams & query_grams) / len(term_grams)
