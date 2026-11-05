"""后台管理路由：全部接口要求管理员权限（require_admin）。

覆盖：概览 / 用户管理 / 书籍上下架 / 入库任务（含失败重试）/ AI 用量统计。
"""

from fastapi import APIRouter, Depends, Query
from redis.asyncio import Redis

from app.core.redis import get_redis
from app.schemas.admin import (
    AdminBookOut,
    AdminBookUpdate,
    AdminUserOut,
    AdminUserUpdate,
    AIStatsOut,
    AdminOverviewOut,
    IngestTaskCreate,
    IngestTaskOut,
)
from app.services.admin_service import AdminService, get_admin_service
from app.services.book_cache import bump_books_cache
from app.services.ingest_service import IngestService, get_ingest_service
from app.services.user_service import User, require_admin

router = APIRouter(
    prefix="/admin",
    tags=["后台管理"],
    dependencies=[Depends(require_admin)],  # 路由组级权限：非管理员一律 403
)


@router.get("/overview", response_model=AdminOverviewOut)
async def overview(admin: AdminService = Depends(get_admin_service)):
    """后台概览：用户数 / 书籍数 / 进行中任务 / 今日 AI 调用"""
    return await admin.overview()


# ================= 用户管理 =================


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(
    query: str = Query(default="", max_length=100, description="按用户名/邮箱模糊搜索"),
    page: int = Query(default=1, ge=1),
    admin: AdminService = Depends(get_admin_service),
):
    users, _total = await admin.list_users(query, page)
    return users


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: int,
    data: AdminUserUpdate,
    admin: AdminService = Depends(get_admin_service),
    operator: User = Depends(require_admin),
):
    """设置/取消管理员，禁用/解禁用户（禁用立即吊销其全部 token）"""
    return await admin.update_user(user_id, data, operator_id=operator.id)


# ================= 书籍上下架 =================


@router.get("/books", response_model=list[AdminBookOut])
async def list_books(
    query: str = Query(default="", max_length=100, description="按书名/作者模糊搜索"),
    only_active: bool = Query(default=False, description="仅看上架书籍（默认全量含下架）"),
    page: int = Query(default=1, ge=1),
    admin: AdminService = Depends(get_admin_service),
):
    books, _total = await admin.list_books(query, only_active=only_active, page=page)
    return books


@router.patch("/books/{book_id}", response_model=AdminBookOut)
async def update_book(
    book_id: int,
    data: AdminBookUpdate,
    admin: AdminService = Depends(get_admin_service),
    redis: Redis = Depends(get_redis),
):
    """上架/下架书籍：下架后书库/搜索/章节接口对普通用户立即不可见"""
    book = await admin.update_book(book_id, data)
    await bump_books_cache(redis)  # 书库内容变化，列表缓存立即失效
    return book


# ================= 入库任务 =================


@router.get("/ingest/tasks", response_model=list[IngestTaskOut])
async def list_tasks(
    limit: int = Query(default=50, ge=1, le=200),
    ingest: IngestService = Depends(get_ingest_service),
):
    """最近的入库任务列表（新任务在前）"""
    return await ingest.list_tasks(limit)


@router.post("/ingest/tasks", response_model=IngestTaskOut, status_code=201)
async def create_task(
    data: IngestTaskCreate,
    ingest: IngestService = Depends(get_ingest_service),
    operator: User = Depends(require_admin),
):
    """创建入库任务：爬取 → 入库 → 切章 → 分块 →（可选）向量化，后台异步执行"""
    return await ingest.create_task(data.gutenberg_id, data.embed, created_by=operator.id)


@router.post("/ingest/tasks/{task_id}/retry", response_model=IngestTaskOut)
async def retry_task(
    task_id: int,
    ingest: IngestService = Depends(get_ingest_service),
):
    """重试失败任务：重置为 pending 重新调度执行，attempts 累加"""
    return await ingest.retry_task(task_id)


# ================= AI 用量统计 =================


@router.get("/stats/ai", response_model=AIStatsOut)
async def ai_stats(
    days: int = Query(default=30, ge=1, le=365, description="统计最近 N 天（UTC）"),
    admin: AdminService = Depends(get_admin_service),
):
    """AI 调用次数 / token 用量 / 成本估算（按场景与按天）"""
    return await admin.ai_stats(days)
