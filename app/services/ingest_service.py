"""书籍入库任务服务：管理员触发的 爬取→入库→切章→分块→向量化 异步任务。

- 任务落库（ingest_tasks 表），执行状态实时可查
- 后台 asyncio 任务执行，串行锁保证同一时间只有一个入库任务在跑
  （BGE-M3 向量化是 CPU 大户，并行只会互相拖慢）
- 失败任务可重试：重置状态为 pending 重新执行，attempts 累加
"""

import asyncio
import traceback
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.scraper import crawl_one
from app.db.database import get_db
from app.models.ingest_task import IngestTask
from app.pipeline import run_ingest

# 后台任务句柄（进程内），用于避免同一任务被并发重复执行
_BG_TASKS: set[asyncio.Task] = set()
# 全局串行锁：入库管线重 CPU（向量化），同一时间只跑一个任务
_INGEST_LOCK = asyncio.Lock()


def _now():
    return datetime.now(timezone.utc)


class IngestService:
    """入库任务管理"""

    def __init__(self, db: AsyncSession):
        self.db = db

    # ---------- 查询 ----------

    async def list_tasks(self, limit: int = 50) -> list[IngestTask]:
        """最近的任务列表（新任务在前）"""
        result = await self.db.execute(
            select(IngestTask).order_by(IngestTask.id.desc()).limit(limit)
        )
        return list(result.scalars().all())

    # ---------- 创建 / 重试 ----------

    async def create_task(self, gutenberg_id: int, embed: bool, created_by: int) -> IngestTask:
        """创建入库任务并立即调度后台执行"""
        task = IngestTask(
            gutenberg_id=gutenberg_id, embed=embed,
            status="pending", created_by=created_by,
        )
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        self._schedule(task.id)
        return task

    async def retry_task(self, task_id: int) -> IngestTask:
        """重试失败任务：仅 failed 状态可重试，重置后重新调度"""
        task = await self.db.get(IngestTask, task_id)
        if task is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"任务 {task_id} 不存在")
        if task.status != "failed":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅失败状态的任务可以重试")
        task.status = "pending"
        task.error = None
        task.finished_at = None
        await self.db.commit()
        await self.db.refresh(task)
        self._schedule(task.id)
        return task

    # ---------- 后台执行 ----------

    def _schedule(self, task_id: int) -> None:
        """调度后台执行（fire-and-forget，异常记录在任务行内）"""
        bg = asyncio.create_task(self._run(task_id))
        _BG_TASKS.add(bg)
        bg.add_done_callback(_BG_TASKS.discard)

    async def _run(self, task_id: int) -> None:
        """任务执行体：pending → running → success / failed

        独立数据库会话：任务生命周期跨越请求边界，不能复用请求级会话。
        """
        from app.db.database import AsyncSessionLocal

        async with _INGEST_LOCK:
            async with AsyncSessionLocal() as db:
                task = await db.get(IngestTask, task_id)
                if task is None or task.status not in ("pending",):
                    return  # 已被删除或不处于待执行状态（如已被重试调度）
                task.status = "running"
                task.attempts += 1
                task.started_at = _now()
                task.error = None
                await db.commit()
                gutenberg_id, embed = task.gutenberg_id, task.embed

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


def get_ingest_service(db: AsyncSession = Depends(get_db)) -> IngestService:
    return IngestService(db)
