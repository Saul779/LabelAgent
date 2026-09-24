"""请求级 trace_id 注入中间件，与 MQ 侧 trace_id（§3.1 v2）贯通。"""

from __future__ import annotations

import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from label_agent.core.tracing import set_trace_id


class TracingMiddleware(BaseHTTPMiddleware):
    """请求级中间件：从请求头读取/生成 trace_id 并注入上下文，响应头回传以便端到端追踪。"""

    async def dispatch(self, request: Request, call_next):
        """透传或生成 trace_id，设置到当前上下文后放行请求，并写回响应头。"""
        trace_id = request.headers.get("x-trace-id", str(uuid.uuid4()))
        set_trace_id(trace_id)
        response = await call_next(request)
        response.headers["x-trace-id"] = trace_id
        return response
