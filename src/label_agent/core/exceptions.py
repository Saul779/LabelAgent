"""统一异常层级，供重试分类（§4.5）与错误码上报使用。"""

from __future__ import annotations


class LabelAgentError(Exception):
    """所有业务异常的基类，携带可对外暴露的 error_code。"""

    error_code: str = "LABEL_AGENT_ERROR"


class RetryableError(LabelAgentError):
    """可重试错误：MQ 短暂不可用、HTTP 超时/限流/5xx、乐观锁冲突等（§4.5）。"""

    error_code = "RETRYABLE_ERROR"


class NonRetryableError(LabelAgentError):
    """不可重试错误：Schema 不兼容、缺失必填字段、非法媒体格式等（§4.5）。"""

    error_code = "NON_RETRYABLE_ERROR"


class NeedReviewError(LabelAgentError):
    """业务待处理：证据不足、敏感候选命中、安全门禁未通过（§4.5）。"""

    error_code = "NEED_REVIEW"


class SupersededError(LabelAgentError):
    """处理中发现更新版本到达，当前 Job 终止发布（§4.3）。"""

    error_code = "SUPERSEDED"


class SchemaValidationError(NonRetryableError):
    """出参/中间结构不符合约定 Schema 时抛出。"""

    error_code = "SCHEMA_VALIDATION_ERROR"


class EvidenceValidationError(NonRetryableError):
    """证据引用校验失败时抛出。"""

    error_code = "EVIDENCE_VALIDATION_ERROR"


class SafetyGateRejectedError(NeedReviewError):
    """新标签安全门禁未通过（§6.2）。"""

    error_code = "SAFETY_GATE_REJECTED"


class SsrfProtectionError(NonRetryableError):
    """媒体 URI 命中私网地址/非白名单域名（§5.1.2、§8）。"""

    error_code = "SSRF_PROTECTION_ERROR"
