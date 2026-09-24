"""健康检查：liveness/readiness，供 K8s 探针使用（见 deploy/k8s）。"""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live")
async def liveness() -> dict:
    """存活探针：进程能响应即返回 ok，供 K8s 判断是否需要重启容器。"""
    return {"status": "ok"}


@router.get("/ready")
async def readiness() -> dict:
    """就绪探针：供 K8s 判断是否可接入流量（生产实现应检查 MQ/TagService 连通性）。"""
    # 生产实现应检查 MQ/TagService 连通性
    return {"status": "ok"}
