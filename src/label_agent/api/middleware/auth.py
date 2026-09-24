"""管理接口鉴权：区别于 MQ 消息来源鉴权（§8），此处保护运维/审核台入口。"""

from __future__ import annotations

from fastapi import Header, HTTPException


async def require_admin_token(x_admin_token: str = Header(...)) -> None:
    """作为路由依赖校验管理凭证是否存在，缺失则拒绝请求（生产实现应对接统一身份/权限系统）。"""
    # 生产实现应对接统一身份/权限系统，此处仅定义校验点
    if not x_admin_token:
        raise HTTPException(status_code=401, detail="缺少管理凭证")
