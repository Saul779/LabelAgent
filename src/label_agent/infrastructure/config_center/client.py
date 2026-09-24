"""ConfigCenterClient：优先读远程配置中心，未接入时回退到 Settings.yaml_config（本地文件）。

保证 configs/*.yaml 与真实配置中心之间可以平滑切换，不改调用方代码。
"""

from __future__ import annotations

from typing import Any

from label_agent.settings import Settings


class ConfigCenterClient:
    """配置中心客户端：读取字符串/JSON/布尔配置。"""

    def __init__(self, settings: Settings) -> None:
        """初始化配置数据源。"""
        self._settings = settings

    def get_str(self, key: str, default: str | None = None) -> str:
        """读取字符串配置项。"""
        value = self._lookup(key)
        if value is None:
            if default is not None:
                return default
            raise KeyError(f"配置项缺失: {key}")
        return str(value)

    def get_json(self, key: str) -> dict[str, Any]:
        """读取 JSON 配置项。"""
        value = self._lookup(key)
        if not isinstance(value, dict):
            raise KeyError(f"配置项缺失或类型不匹配: {key}")
        return value

    def get_bool(self, key: str, default: bool = False) -> bool:
        """读取布尔配置项。"""
        value = self._lookup(key)
        return bool(value) if value is not None else default

    def _lookup(self, dotted_key: str) -> Any | None:
        """按键查找原始配置值。"""
        node: Any = self._settings.yaml_config
        for part in dotted_key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        return node
