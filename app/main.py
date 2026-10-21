from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.routes.ask import router as ask_router
from app.api.routes.auth import router as auth_router
from app.api.routes.book import router as book_router
from app.api.routes.level_test import router as level_test_router
from app.api.routes.reading import router as reading_router
from app.api.routes.translate import router as translate_router
from app.db.database import Base, engine
from app.models import (  # noqa: F401 确保模型注册到 metadata
    book,
    book_chapter,
    book_chunk,
    level_test_result,
    reading_progress,
    translation_record,
    user,
)
from app.schemas.user import UserOut
from app.services.user_service import get_current_user


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 简化处理：启动时先启用 pgvector 扩展与全文索引再自动建表；生产环境建议改用 Alembic 迁移
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.execute(text("ALTER TABLE IF EXISTS books ADD COLUMN IF NOT EXISTS cover_url VARCHAR(512)"))
        await conn.run_sync(Base.metadata.create_all)
        # 全文检索（ts_rank）关键词路的表达式 GIN 索引（表达式必须与查询中的完全一致才能命中索引）
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_book_chunks_fts "
                "ON book_chunks USING gin (to_tsvector('english', chunk_text))"
            )
        )
    yield


app = FastAPI(title="English Reading Agent", lifespan=lifespan)

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


@app.get("/me", response_model=UserOut, tags=["认证"])
async def me(current_user=Depends(get_current_user)):
    """获取当前登录用户信息（需 Authorization: Bearer <token>）"""
    return current_user
