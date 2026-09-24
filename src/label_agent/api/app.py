"""FastAPI 应用工厂：装配运维/管理路由，不承载核心业务流程（核心流程见 application/workers）。"""

from __future__ import annotations

from fastapi import FastAPI

from label_agent.api.middleware.tracing import TracingMiddleware
from label_agent.api.routers import health, replay


def create_app() -> FastAPI:
    """组装 FastAPI 应用：挂载 trace 中间件与健康检查/重放路由。"""
    app = FastAPI(title="Label Agent Admin API", version="0.1.0")
    app.add_middleware(TracingMiddleware)

    app.include_router(health.router)
    app.include_router(replay.router)

    return app
