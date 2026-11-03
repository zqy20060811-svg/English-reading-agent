"""后台管理业务逻辑：用户管理 / 书籍上下架 / 入库任务 / AI 用量统计"""

from datetime import date, datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.db.database import get_db
from app.models.book import Book
from app.models.ingest_task import IngestTask
from app.models.llm_usage import LLMUsageLog
from app.models.user import User
from app.repositories.token_repository import TokenRepository
from app.schemas.admin import (
    AdminUserUpdate,
    AdminBookUpdate,
    AIStatsOut,
    DailyUsageOut,
    SceneUsageOut,
)
from app.services.usage_service import estimate_cost_usd


class AdminService:
    """管理员后台操作（路由层已用 require_admin 保证权限）"""

    def __init__(self, db: AsyncSession, redis: Redis):
        self.db = db
        self.redis = redis

    # ================= 概览 =================

    async def overview(self) -> dict:
        """管理后台首页概览指标"""
        total_users = (
            await self.db.execute(select(func.count()).select_from(User))
        ).scalar_one()
        total_books, active_books = (
            await self.db.execute(
                select(
                    func.count(Book.id),
                    func.count(Book.id).filter(Book.is_active == True),  # noqa: E712
                ).select_from(Book)
            )
        ).one()
        running_tasks = (
            await self.db.execute(
                select(func.count()).select_from(IngestTask)
                .where(IngestTask.status.in_(("pending", "running")))
            )
        ).scalar_one()
        today = datetime.now(timezone.utc).date()
        ai_calls_today = (
            await self.db.execute(
                select(func.count()).select_from(LLMUsageLog)
                .where(cast(LLMUsageLog.created_at, Date) == today)
            )
        ).scalar_one()
        return {
            "total_users": total_users,
            "total_books": total_books,
            "active_books": active_books,
            "running_or_pending_tasks": running_tasks,
            "ai_calls_today": ai_calls_today,
        }

    # ================= 用户管理 =================

    async def list_users(self, query: str, page: int, page_size: int = 20) -> tuple[list[User], int]:
        """用户列表：按用户名/邮箱模糊搜索 + 分页，返回 (列表, 总数)"""
        stmt = select(User).order_by(User.id)
        count_stmt = select(func.count()).select_from(User)
        q = query.strip()
        if q:
            pattern = f"%{q}%"
            cond = User.username.ilike(pattern) | User.email.ilike(pattern)
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)
        total = (await self.db.execute(count_stmt)).scalar_one()
        rows = await self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
        return list(rows.scalars().all()), total

    async def update_user(
        self, user_id: int, data: AdminUserUpdate, operator_id: int
    ) -> User:
        """修改用户管理员/禁用状态；禁用立即吊销其全部 token"""
        user = await self.db.get(User, user_id)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"用户 {user_id} 不存在")
        # 防呆：管理员不能取消自己的管理员身份（避免唯一管理员把自己锁在门外）
        if data.is_admin is False and user.id == operator_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能取消自己的管理员权限")
        if data.is_admin is not None:
            user.is_admin = data.is_admin
        if data.is_disabled is not None:
            if data.is_disabled and user.id == operator_id:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能禁用自己的账号")
            user.is_disabled = data.is_disabled
            if data.is_disabled:
                # 禁用即吊销全部 token：已登录会话立即失效
                repo = TokenRepository(self.redis)
                await repo.revoke_all_for_user(user_id)
                await repo.revoke_all_refresh_for_user(user_id)
        await self.db.commit()
        await self.db.refresh(user)
        return user

    # ================= 书籍上下架 =================

    async def list_books(
        self, query: str, only_active: bool = False, page: int = 1, page_size: int = 20
    ) -> tuple[list[Book], int]:
        """后台书籍列表：默认含下架书籍（only_active=False）"""
        stmt = select(Book).order_by(Book.id)
        count_stmt = select(func.count()).select_from(Book)
        q = query.strip()
        if q:
            pattern = f"%{q}%"
            cond = Book.title.ilike(pattern) | Book.author.ilike(pattern)
            stmt = stmt.where(cond)
            count_stmt = count_stmt.where(cond)
        if only_active:
            stmt = stmt.where(Book.is_active == True)  # noqa: E712
            count_stmt = count_stmt.where(Book.is_active == True)  # noqa: E712
        total = (await self.db.execute(count_stmt)).scalar_one()
        rows = await self.db.execute(stmt.offset((page - 1) * page_size).limit(page_size))
        return list(rows.scalars().all()), total

    async def update_book(self, book_id: int, data: AdminBookUpdate) -> Book:
        """上架/下架书籍；下架后书库/搜索/章节接口立即对普通用户不可见"""
        book = await self.db.get(Book, book_id)
        if book is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"书籍 {book_id} 不存在")
        book.is_active = data.is_active
        await self.db.commit()
        await self.db.refresh(book)
        return book

    # ================= AI 用量统计 =================

    async def ai_stats(self, days: int = 30) -> AIStatsOut:
        """近 N 天（按 UTC 日）的调用次数 / token / 成本估算"""
        since_date = date.today() - timedelta(days=days - 1)
        since_dt = datetime(since_date.year, since_date.month, since_date.day, tzinfo=timezone.utc)

        scene_rows = (
            await self.db.execute(
                select(
                    LLMUsageLog.scene,
                    func.count().label("calls"),
                    func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0).label("pt"),
                    func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0).label("ct"),
                )
                .where(LLMUsageLog.created_at >= since_dt)
                .group_by(LLMUsageLog.scene)
            )
        ).all()

        day_rows = (
            await self.db.execute(
                select(
                    cast(LLMUsageLog.created_at, Date).label("day"),
                    func.count().label("calls"),
                    func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0).label("pt"),
                    func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0).label("ct"),
                )
                .where(LLMUsageLog.created_at >= since_dt)
                .group_by(cast(LLMUsageLog.created_at, Date))
                .order_by(cast(LLMUsageLog.created_at, Date))
            )
        ).all()

        by_scene = [
            SceneUsageOut(
                scene=r.scene, calls=r.calls, prompt_tokens=r.pt, completion_tokens=r.ct,
                cost_usd=estimate_cost_usd(r.pt, r.ct),
            )
            for r in scene_rows
        ]
        by_day = [
            DailyUsageOut(
                day=str(r.day), calls=r.calls, prompt_tokens=r.pt, completion_tokens=r.ct,
                cost_usd=estimate_cost_usd(r.pt, r.ct),
            )
            for r in day_rows
        ]
        return AIStatsOut(
            days=days,
            total_calls=sum(s.calls for s in by_scene),
            total_prompt_tokens=sum(s.prompt_tokens for s in by_scene),
            total_completion_tokens=sum(s.completion_tokens for s in by_scene),
            total_cost_usd=round(sum(s.cost_usd for s in by_scene), 4),
            by_scene=by_scene,
            by_day=by_day,
        )


def get_admin_service(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> AdminService:
    return AdminService(db, redis)
