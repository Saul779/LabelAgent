"""ToolRegistry：注册可用 Tool，并导出 function-calling 声明列表。"""

from __future__ import annotations

from typing import Any

from label_agent.tools.base import Tool


class ToolRegistry:
    """工具注册表：按名查找并导出函数声明。"""

    def __init__(self) -> None:
        """初始化空工具表。"""
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        """注册工具实例。"""
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        """按名称获取工具。"""
        return self._tools[name]

    def function_declarations(self) -> list[dict[str, Any]]:
        """导出供模型 Function Calling 使用的声明列表。"""
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters_schema,
            }
            for tool in self._tools.values()
        ]
