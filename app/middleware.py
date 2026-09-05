"""FastAPI 中间件：请求日志、CORS、错误处理和 request_id 追踪。"""

import logging
import time
import uuid
from typing import Callable, Awaitable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.utils.logger import get_request_id, set_request_id

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 请求 ID 中间件
# ---------------------------------------------------------------------------


class RequestIDMiddleware(BaseHTTPMiddleware):
    """为每个请求注入唯一请求 ID 的中间件。

    request_id 会通过 contextvars 传递到下游异步任务，
    这样后台研究流程也能带着同一个 ID 打日志。
    响应头中会返回 X-Request-ID，方便前端或排查工具追踪请求。
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable]
    ):
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:12])
        set_request_id(request_id)

        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response


# ---------------------------------------------------------------------------
# 请求日志中间件
# ---------------------------------------------------------------------------


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """记录每个请求的方法、路径、状态码和耗时。"""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable]
    ):
        start_time = time.monotonic()
        response = await call_next(request)
        duration_ms = (time.monotonic() - start_time) * 1000
        logger.info(
            "%s %s -> %s (%.1fms)",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )
        return response


# ---------------------------------------------------------------------------
# 错误处理中间件
# ---------------------------------------------------------------------------


class ErrorHandlingMiddleware(BaseHTTPMiddleware):
    """捕获未处理异常，并统一返回 500 JSON 响应。"""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable]
    ):
        try:
            response = await call_next(request)
            return response
        except Exception as exc:
            logger.exception("Unhandled exception processing %s %s", request.method, request.url.path)
            return JSONResponse(
                status_code=500,
                content={
                    "detail": "Internal server error",
                    "error": str(exc),
                },
            )


# ---------------------------------------------------------------------------
# 中间件注册辅助函数
# ---------------------------------------------------------------------------


def register_middleware(app: FastAPI) -> None:
    """在 FastAPI 应用上注册所有中间件。

    注册顺序很重要：错误处理包住所有逻辑，请求日志包住业务逻辑，
    CORS 在 ASGI 层处理跨域。

    参数：
        app: FastAPI 应用实例。
    """
    # CORS：允许 Vite 开发服务和本地后端地址访问。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:8000",
            "http://127.0.0.1:8000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 请求 ID：即使错误响应也能带上追踪 ID。
    app.add_middleware(RequestIDMiddleware)

    # 请求日志。
    app.add_middleware(RequestLoggingMiddleware)

    # 错误处理：最外层，捕获所有未处理异常。
    app.add_middleware(ErrorHandlingMiddleware)
