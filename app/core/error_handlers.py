"""全局统一错误响应：所有错误归一为 {detail, code} 结构，detail 保持前端兼容"""

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.services.quota_service import QuotaExceededError


def register_error_handlers(app: FastAPI) -> None:
    """在 FastAPI 应用上注册全局异常处理器"""

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": f"http_{exc.status_code}"},
            headers=exc.headers,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        # 422 归一为可读字符串（原来是无结构的数组），detail 字段保持前端解析兼容
        errors = exc.errors()
        if errors:
            first = errors[0]
            loc = ".".join(str(x) for x in first.get("loc", []) if x != "body")
            detail = f"请求参数不正确：{loc} {first.get('msg', '')}".strip()
        else:
            detail = "请求参数不正确"
        return JSONResponse(
            status_code=422,
            content={"detail": detail, "code": "validation_error"},
        )

    @app.exception_handler(QuotaExceededError)
    async def quota_exceeded_handler(request: Request, exc: QuotaExceededError):
        return JSONResponse(
            status_code=429,
            content={"detail": str(exc), "code": "quota_exceeded"},
        )

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception):
        # 兜底：未预期异常不向客户端泄漏堆栈细节
        return JSONResponse(
            status_code=500,
            content={"detail": "服务器内部错误，请稍后重试", "code": "internal_error"},
        )
