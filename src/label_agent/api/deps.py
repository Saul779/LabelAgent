"""FastAPI 依赖注入：从 core.di.Container 派生请求级依赖。"""

from __future__ import annotations

from label_agent.application.use_cases.trigger_profile_job import TriggerProfileJobUseCase
from label_agent.application.use_cases.trigger_replay import TriggerReplayUseCase
from label_agent.settings import get_settings


def get_trigger_replay_use_case() -> TriggerReplayUseCase:
    """回放用例占位：正式装配前保持显式未实现。"""
    get_settings().validate_runtime()
    raise NotImplementedError


def get_trigger_profile_job_use_case() -> TriggerProfileJobUseCase:
    """画像触发用例占位：正式装配前保持显式未实现。"""
    get_settings().validate_runtime()
    raise NotImplementedError
