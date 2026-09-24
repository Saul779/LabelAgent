"""领域层专用错误（区别于 core.exceptions 的运行时/基础设施异常分类）。"""

from __future__ import annotations

from label_agent.core.exceptions import LabelAgentError


class InvalidProposalError(LabelAgentError):
    """SemanticProposal 引用了不存在的候选 ID，或结构不满足契约。"""

    error_code = "INVALID_PROPOSAL"


class DuplicateCanonicalTagError(LabelAgentError):
    """同一 canonical_tag_id 簇内出现多条候选，违反去重契约（Q015）。"""

    error_code = "DUPLICATE_CANONICAL_TAG"
