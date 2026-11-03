from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes.ask import router as ask_router
from app.api.routes.admin import router as admin_router
from app.api.routes.auth import router as auth_router
from app.api.routes.book import router as book_router
from app.api.routes.bookmark import router as bookmark_router
from app.api.routes.level_test import router as level_test_router
from app.api.routes.me import router as me_router
from app.api.routes.reading import router as reading_router
from app.api.routes.translate import router as translate_router
from app.api.routes.vocabulary import router as vocabulary_router
from app.core.error_handlers import register_error_handlers
from app.schemas.user import UserOut
from app.services.user_service import get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 建表与索引统一由 Alembic 迁移管理（alembic upgrade head），启动时不再做 DDL
    yield


app = FastAPI(title="English Reading Agent", lifespan=lifespan)
register_error_handlers(app)  # 全局统一错误响应 {detail, code}

# 允许本地前端（任意端口）跨域访问；前端正式部署后再收紧来源
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(book_router)
app.include_router(reading_router)
app.include_router(ask_router)
app.include_router(level_test_router)
app.include_router(translate_router)
app.include_router(me_router)
app.include_router(vocabulary_router)
app.include_router(bookmark_router)
app.include_router(admin_router)


@app.get("/me", response_model=UserOut, tags=["认证"])
async def me(current_user=Depends(get_current_user)):
    """获取当前登录用户信息（需 Authorization: Bearer <token>）"""
    return current_user
