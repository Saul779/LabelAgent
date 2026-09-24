"""PostValidation：检查本次结果引用的新建标签 vector_state（§6.3）。

若仍为 PENDING，Job 进入重试等待，不发布 TaggingCompleted。
"""

from __future__ import annotations

from label_agent.core.context import JobContext
from label_agent.domain.models.s3_result import ContentLabelResult
from label_agent.domain.models.tag import VectorState


class PostValidator:
    """推理后校验：Schema、证据引用、安全策略等。"""

    def validate(self, ctx: JobContext, result: ContentLabelResult) -> None:
        """对场景出参执行后置校验。"""
        for tag in result.tags:
            if tag.vector_state == VectorState.FAILED.value:
                raise RuntimeError(f"标签向量生成失败: {tag.tag_id}")
