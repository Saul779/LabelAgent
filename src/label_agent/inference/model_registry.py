"""多模型注册与切换：按 alias（primary/fallback/local）解析到具体 provider+model_name。

配置来源：configs/base.yaml `inference.models`。切换模型/供应商只需改配置，
不改调用方代码（调用方只感知 alias）。
"""

from __future__ import annotations

from dataclasses import dataclass

from label_agent.inference.providers.base import ModelProvider


@dataclass
class ModelBinding:
    """模型别名到 Provider + 具体模型名的绑定。"""

    alias: str
    provider: ModelProvider
    model_name: str


class ModelRegistry:
    """管理可用模型别名，供 LlmGateway 解析实际调用目标。"""

    def __init__(self, default_alias: str) -> None:
        """指定默认模型别名。"""
        self._default_alias = default_alias
        self._bindings: dict[str, ModelBinding] = {}

    def register(self, binding: ModelBinding) -> None:
        """注册一个模型绑定。"""
        self._bindings[binding.alias] = binding

    def resolve(self, alias: str | None = None) -> ModelBinding:
        """按别名解析绑定；未指定时使用默认别名。"""
        key = alias or self._default_alias
        try:
            return self._bindings[key]
        except KeyError as exc:
            raise ValueError(f"未注册的模型 alias: {key}") from exc
