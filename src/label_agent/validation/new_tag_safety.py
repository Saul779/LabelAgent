"""新标签写入前的同步安全校验。"""

from __future__ import annotations

import unicodedata

from label_agent.domain.errors import InvalidProposalError
from label_agent.validation.safety.injection_detector import InjectionDetector
from label_agent.validation.safety.pii_detector import PiiDetector
from label_agent.validation.safety.sensitive_word_filter import SensitiveWordFilter


def normalize_tag_name(name: str) -> str:
    """使用 NFKC 和大小写折叠生成查重与幂等名称。"""
    return "".join(unicodedata.normalize("NFKC", name).casefold().split())


def assert_new_tag_safe(
    proposed_name: str,
    domain: str,
    *,
    allowed_domains: set[str],
    sensitive_word_filter: SensitiveWordFilter,
    pii_detector: PiiDetector,
    injection_detector: InjectionDetector,
) -> None:
    """校验新标签名称、领域及敏感内容，不执行任何外部写操作。"""
    normalized_name = normalize_tag_name(proposed_name)
    if not normalized_name or len(normalized_name) > 40:
        raise InvalidProposalError("新标签名称长度必须为 1~40 个有效字符")
    if domain not in allowed_domains:
        raise InvalidProposalError(f"新标签 domain 不在白名单中: {domain}")
    sensitive_word_filter.assert_clean(proposed_name)
    pii_detector.assert_clean(proposed_name)
    injection_detector.assert_clean(proposed_name)
