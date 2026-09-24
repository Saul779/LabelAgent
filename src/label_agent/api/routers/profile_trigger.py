"""S4 手动触发接口：当前只支持手动触发单次任务，不实现定时调度（§5.4）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from label_agent.api.deps import get_trigger_profile_job_use_case
from label_agent.api.middleware.auth import require_admin_token
from label_agent.application.use_cases.trigger_profile_job import TriggerProfileJobUseCase
from label_agent.schemas.job_schema import ProfileTriggerRequest, ProfileTriggerResponse

router = APIRouter(prefix="/profile", tags=["profile"], dependencies=[Depends(require_admin_token)])


@router.post("/trigger", response_model=ProfileTriggerResponse)
async def trigger_profile_job(
    request: ProfileTriggerRequest,
    use_case: Annotated[
        TriggerProfileJobUseCase,
        Depends(get_trigger_profile_job_use_case),
    ],
) -> ProfileTriggerResponse:
    """为指定用户手动触发一次 S4 画像更新任务，返回新建的 job_id。"""
    job_id = await use_case.execute(request.user_id, request.operator)
    return ProfileTriggerResponse(job_id=job_id)
