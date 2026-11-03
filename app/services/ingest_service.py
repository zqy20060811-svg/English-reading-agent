"""书籍入库任务服务：管理员触发的 爬取→入库→切章→分块→向量化 异步任务。

- 任务落库（ingest_tasks 表），执行状态实时可查
- 后台 asyncio 任务执行，串行锁保证同一时间只有一个入库任务在跑
  （BGE-M3 向量化是 CPU 大户，并行只会互相拖慢）
- 可靠性保障：
  * 原子领取：UPDATE ... WHERE status='pending'，重复调度/多进程都不会重复执行
  * 启动恢复：进程重启后 running 任务标记为 failed（可重试），pending 任务重新调度
  * 超时兜底：running 超过阈值小时数视为挂死，懒惰标记为 failed（可重试）
  * 重复防护：同书同时只允许一个进行中任务（应用层校验 + 部分唯一索引兜底）
- 失败任务可重试：重置状态为 pending 重新执行，attempts 累加
"""

import asyncio
import traceback
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.scraper import crawl_one
from app.db.database import get_db
from app.models.book import Book
from app.models.ingest_task import IngestTask
from app.pipeline import run_ingest

# 全局串行锁：入库管线重 CPU（向量化），同一时间只跑一个任务
_INGEST_LOCK = asyncio.Lock()
# running 任务超时阈值（小时）：超过视为挂死，懒惰标记失败
STALE_RUNNING_HOURS = 6

# 进行中（占用书号）的状态集合，与部分唯一索引 uq_ingest_tasks_active_book 保持一致
_ACTIVE_STATUSES = ("pending", "running")


def _now():
    return datetime.now(timezone.utc)


# 后台任务句柄（进程内），持有强引用避免任务被 GC，完成后自动移除
_BG_TASKS: set[asyncio.Task] = set()


def schedule_task(task_id: int) -> None:
    """调度后台执行（fire-and-forget，异常记录在任务行内）"""
    bg = asyncio.create_task(_run(task_id))
    _BG_TASKS.add(bg)
    bg.add_done_callback(_BG_TASKS.discard)


async def recover_interrupted_tasks() -> list[int]:
    """应用启动时恢复中断任务，返回需要重新调度的 pending 任务 id 列表。

    - running → failed：上次进程退出时正在执行的任务已丢失执行体，标记为失败
      （error 注明原因，管理员可安全重试），避免永久卡在 running
    - pending 保持不变：任务尚未开始，由调用方重新调度（领取是原子的，重复调度安全）
    """
    from app.db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(
            update(IngestTask)
            .where(IngestTask.status == "running")
            .values(
                status="failed",
                error="服务重启导致任务中断，可安全重试",
                finished_at=_now(),
            )
        )
        result = await db.execute(
            select(IngestTask.id).where(IngestTask.status == "pending").order_by(IngestTask.id)
        )
        pending_ids = list(result.scalars().all())
        await db.commit()
    return pending_ids


async def _run(task_id: int) -> None:
    """任务执行体：pending → running → success / failed

    独立数据库会话：任务生命周期跨越请求边界，不能复用请求级会话。
    """
    from app.db.database import AsyncSessionLocal

    async with _INGEST_LOCK:
        async with AsyncSessionLocal() as db:
            # 原子领取：仅当任务仍处于 pending 时置为 running，
            # 重复调度或多进程同时调度时后领取者 rowcount=0 直接返回
            result = await db.execute(
                update(IngestTask)
                .where(IngestTask.id == task_id, IngestTask.status == "pending")
                .values(
                    status="running",
                    attempts=IngestTask.attempts + 1,
                    started_at=_now(),
                    error=None,
                )
            )
            await db.commit()
            if result.rowcount == 0:
                return  # 已被其他调度领取、或任务已删除/非待执行状态
            row = await db.execute(
                select(IngestTask.gutenberg_id, IngestTask.embed).where(IngestTask.id == task_id)
            )
            gutenberg_id, embed = row.one()

        try:
            # 1) 爬取（若本地已有该书数据，重新下载覆盖为最新版本）
            await asyncio.to_thread(crawl_one, gutenberg_id)
            # 2) 入库管线：书籍同步 + 章节切分 + 分块 +（可选）向量化
            await run_ingest([gutenberg_id], embed=embed)
            async with AsyncSessionLocal() as db:
                task = await db.get(IngestTask, task_id)
                if task:
                    task.status = "success"
                    task.finished_at = _now()
                    await db.commit()
        except Exception as exc:
            async with AsyncSessionLocal() as db:
                task = await db.get(IngestTask, task_id)
                if task:
                    task.status = "failed"
                    task.error = f"{exc}\n{traceback.format_exc()[-1500:]}"
                    task.finished_at = _now()
                    await db.commit()


class IngestService:
    """入库任务管理"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- 查询 ----------

    async def list_tasks(self, limit: int = 50) -> list[IngestTask]:
        """最近的任务列表（新任务在前）。

        查询前懒惰执行超时兜底：running 超过阈值视为挂死，标记失败可重试。
        """
        cutoff = _now() - timedelta(hours=STALE_RUNNING_HOURS)
        await self.db.execute(
            update(IngestTask)
            .where(IngestTask.status == "running", IngestTask.started_at < cutoff)
            .values(
                status="failed",
                error=f"任务执行超过 {STALE_RUNNING_HOURS} 小时未完成，已自动标记失败，可安全重试",
                finished_at=_now(),
            )
        )
        await self.db.commit()
        result = await self.db.execute(
            select(IngestTask).order_by(IngestTask.id.desc()).limit(limit)
        )
        return list(result.scalars().all())

    # ---------- 创建 / 重试 ----------

    async def _find_active_task(
        self, gutenberg_id: int, exclude_id: int | None = None
    ) -> IngestTask | None:
        """查找该书正在进行中（pending/running）的任务，可排除指定任务"""
        stmt = select(IngestTask).where(
            IngestTask.gutenberg_id == gutenberg_id,
            IngestTask.status.in_(_ACTIVE_STATUSES),
        )
        if exclude_id is not None:
            stmt = stmt.where(IngestTask.id != exclude_id)
        return (await self.db.execute(stmt.order_by(IngestTask.id))).scalars().first()

    async def create_task(self, gutenberg_id: int, embed: bool, created_by: int) -> IngestTask:
        """创建入库任务并立即调度后台执行（含重复提交防护）"""
        # 防护 1：该书已有进行中任务，等待其完成或失败
        active = await self._find_active_task(gutenberg_id)
        if active:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"书号 {gutenberg_id} 已有进行中的入库任务（#{active.id}，{active.status}），"
                "请等待其完成或失败后再提交",
            )
        # 防护 2：书籍已在书库，拒绝重复入库（如需更新内容属后续功能）
        book = (
            await self.db.execute(select(Book).where(Book.gutenberg_id == gutenberg_id))
        ).scalars().first()
        if book:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"《{book.title}》已在书库中，无需重复入库",
            )
        task = IngestTask(
            gutenberg_id=gutenberg_id, embed=embed,
            status="pending", created_by=created_by,
        )
        self.db.add(task)
        try:
            await self.db.commit()
        except IntegrityError:
            # 并发提交竞态兜底：部分唯一索引 uq_ingest_tasks_active_book 拒绝第二个进行中任务
            await self.db.rollback()
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"书号 {gutenberg_id} 已有进行中的入库任务，请勿重复提交",
            )
        await self.db.refresh(task)
        schedule_task(task.id)
        return task

    async def retry_task(self, task_id: int) -> IngestTask:
        """重试失败任务：仅 failed 状态可重试，重置后重新调度"""
        task = await self.db.get(IngestTask, task_id)
        if task is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"任务 {task_id} 不存在")
        if task.status != "failed":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅失败状态的任务可以重试")
        # 同书防重：另一任务正在处理该书时不允许同时重试（避免部分唯一索引冲突）
        dup = await self._find_active_task(task.gutenberg_id, exclude_id=task.id)
        if dup:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"书号 {task.gutenberg_id} 另有进行中的任务（#{dup.id}，{dup.status}），暂时无法重试",
            )
        task.status = "pending"
        task.error = None
        task.finished_at = None
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"书号 {task.gutenberg_id} 已有进行中的入库任务，暂时无法重试",
            )
        await self.db.refresh(task)
        schedule_task(task.id)
        return task


def get_ingest_service(db: AsyncSession = Depends(get_db)) -> IngestService:
    return IngestService(db)
