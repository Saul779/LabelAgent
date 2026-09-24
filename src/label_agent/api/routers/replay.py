"""DLQ 重放触发接口：不得用新 task_id 绕过幂等键，重放建立 replay_generation（§4.5）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from label_agent.api.deps import get_trigger_replay_use_case
from label_agent.api.middleware.auth import require_admin_token
from label_agent.application.use_cases.trigger_replay import TriggerReplayUseCase
from label_agent.schemas.replay_schema import ReplayRequest, ReplayResponse

router = APIRouter(prefix="/replay", tags=["replay"], dependencies=[Depends(require_admin_token)])


@router.post("", response_model=ReplayResponse)
async def trigger_replay(
    request: ReplayRequest,
    use_case: Annotated[
        TriggerReplayUseCase,
        Depends(get_trigger_replay_use_case),
    ],
) -> ReplayResponse:
    """触发指定 Job 的 DLQ 重放，复用原幂等键并生成新的 replay_generation。"""
    replay_generation = await use_case.execute(request.job_id, request.operator)
    return ReplayResponse(job_id=request.job_id, replay_generation=replay_generation)
