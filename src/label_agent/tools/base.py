"""Tool 协议：name + JSON Schema 参数声明 + 只读 invoke。"""

from __future__ import annotations

from typing import Any, Protocol


class Tool(Protocol):
    """Agent 可调用工具的抽象基类。"""

    name: str
    description: str
    parameters_schema: dict[str, Any]

    async def invoke(self, **kwargs: Any) -> Any: ...
