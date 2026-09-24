"""TriggerProfileJob 用例：S4 当前只支持手动触发单次任务，不实现定时调度（§5.4）。"""

from __future__ import annotations

from label_agent.application.orchestrator import Orchestrator


class TriggerProfileJobUseCase:
    """触发 S4 画像类 Job。"""

    def __init__(self, orchestrator: Orchestrator) -> None:
        """注入画像任务创建依赖。"""
        self._orchestrator = orchestrator

    async def execute(self, user_id: str, operator: str) -> str:
        """人工/运营触发单次画像打标任务，返回 job_id。"""
        raise NotImplementedError
