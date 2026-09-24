"""Job 内部终态与管线阶段。

`outcome` 仅用于内部映射与审计，不直接对外暴露；对外映射规则见 receipt.py。
执行进度不再落本地库，Kafka 分区所有权承担多实例互斥。
"""

from __future__ import annotations

from enum import Enum


class JobPhase(str, Enum):
    """Job 处理阶段枚举。"""

    LOAD = "LOAD"
    PERCEIVE = "PERCEIVE"
    RETRIEVE = "RETRIEVE"
    PROPOSE = "PROPOSE"
    RESOLVE = "RESOLVE"
    PRE_VALIDATE = "PRE_VALIDATE"
    COMMIT = "COMMIT"
    VECTORIZE = "VECTORIZE"
    POST_VALIDATE = "POST_VALIDATE"
    PUBLISH = "PUBLISH"


class JobOutcome(str, Enum):
    """Job 终态结果枚举。"""

    SUCCEEDED = "SUCCEEDED"
    NEED_REVIEW = "NEED_REVIEW"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"
