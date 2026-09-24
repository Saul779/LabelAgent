"""PromptManager：按 scene + prompt_version 加载模板并渲染变量。"""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Template

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"


class PromptNotFoundError(Exception):
    """指定 scene/prompt_version 的模板文件不存在时抛出。"""


class PromptManager:
    """按 scene + prompt_version 加载 YAML 模板并用 Jinja2 渲染 system/user Prompt。"""

    def load(self, scene: str, prompt_version: str) -> dict:
        """从 templates 目录加载指定场景与版本的 Prompt YAML。"""
        path = _TEMPLATES_DIR / scene.lower() / f"{prompt_version}.yaml"
        if not path.exists():
            raise PromptNotFoundError(f"未找到 Prompt 模板: {path}")
        return yaml.safe_load(path.read_text(encoding="utf-8"))

    def render(self, scene: str, prompt_version: str, variables: dict) -> tuple[str, str]:
        """加载模板并渲染变量，返回 (system_prompt, user_prompt)。"""
        spec = self.load(scene, prompt_version)
        system_prompt = Template(spec["system"]).render(**variables)
        user_prompt = Template(spec["user"]).render(**variables)
        return system_prompt, user_prompt
