"""标签—向量一致性状态机（§6.3）：区分“正式生效”（lifecycle_status）与
“可参与召回”（vector_state），避免无向量标签进入 ANN。
"""

from __future__ import annotations

from label_agent.domain.models.s3_result import ContentLabelResult
from label_agent.domain.models.tag import VectorState


def is_publishable(result: ContentLabelResult) -> bool:
    """新建标签向量仍为 PENDING 时不得发布结果，避免不可召回标签提前流入搜索/推荐。"""
    return all(tag.vector_state != VectorState.PENDING.value for tag in result.tags)
