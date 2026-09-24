"""EnvelopeParser：统一解析 v1 字段；v2 扩展字段安全读取，缺失时降级（§3.1）。

协议冻结后只需替换本实现，不改动调用方（application.process_task）。
"""

from __future__ import annotations

from typing import Any

from label_agent.domain.models.envelope import EnvelopeV2Extension, ParsedEnvelope, TaskEnvelopeV1


class EnvelopeParser:
    """将原始 MQ 消息解析为领域 EventEnvelope。"""

    protocol_version: str = "v1"

    def parse(self, raw_message: dict[str, Any]) -> ParsedEnvelope:
        """解析并校验消息信封。"""
        v1 = TaskEnvelopeV1.model_validate(raw_message)
        v2 = EnvelopeV2Extension.model_validate(v1.payload)

        degraded_idempotency = v2.event_id is None
        version_protected = v2.biz_id is not None and v2.data_version is not None

        return ParsedEnvelope(
            v1=v1,
            v2=v2,
            degraded_idempotency=degraded_idempotency,
            version_protected=version_protected,
        )
