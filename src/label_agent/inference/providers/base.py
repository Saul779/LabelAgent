"""ModelProvider 协议：所有 LLM 供应商适配的统一入口。"""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class ModelCompletionRequest(BaseModel):
    """一次模型补全请求的统一入参结构（含可选图片与 JSON Schema）。"""

    system_prompt: str
    user_prompt: str
    response_schema: dict[str, Any] | None = None  # 用于结构化输出/JSON Mode
    temperature: float = 0.0
    max_tokens: int = 1024
    image_urls: list[str] | None = Field(
        default=None,
        description="多模态图片 URL（http(s) 或 data URL），供 vision 模型使用",
    )


class ModelCompletionResult(BaseModel):
    """模型补全原始出参封装（文本与用量等元数据）。"""

    raw_text: str
    model_name: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


class ModelProvider(Protocol):
    """模型 Provider 抽象接口。"""

    provider_name: str

    async def complete(
        self,
        model_name: str,
        request: ModelCompletionRequest,
    ) -> ModelCompletionResult: ...
