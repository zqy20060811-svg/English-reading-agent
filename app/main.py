from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy import text

from app.api.routes.ask import router as ask_router
from app.api.routes.auth import router as auth_router
from app.api.routes.book import router as book_router
from app.api.routes.reading import router as reading_router
from app.db.database import Base, engine
from app.models import book, book_chapter, book_chunk, reading_progress, user  # noqa: F401 确保模型注册到 metadata
from app.schemas.user import UserOut
from app.services.user_service import get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 简化处理：启动时先启用 pgvector 扩展再自动建表；生产环境建议改用 Alembic 迁移
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="English Reading Agent", lifespan=lifespan)

app.include_router(auth_router)
app.include_router(book_router)
app.include_router(reading_router)
app.include_router(ask_router)


@app.get("/me", response_model=UserOut, tags=["认证"])
async def me(current_user=Depends(get_current_user)):
    """获取当前登录用户信息（需 Authorization: Bearer <token>）"""
    return current_user
