"""TriggerReplay 用例：DLQ 重放需复用原幂等键或建立 replay_generation。"""

from __future__ import annotations


class TriggerReplayUseCase:
    """触发 Job 重放（按历史输入重新跑管线）。"""

    async def execute(self, job_id: str, operator: str) -> str:
        """返回新的 replay_generation 标识。"""
        raise NotImplementedError
