"""个人书籍 AI 全书分析：任务管理业务层（查询/创建/取消）。

所有接口强制 user_id 归属校验：他人的任务/结果与不存在的统一 404。
"""

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.database import get_db
from app.models.personal_analysis import (
    PersonalAnalysisTask,
    PersonalBookAnalysis,
    PersonalChapterAnalysis,
)
from app.models.personal_book import PersonalBook
from app.models.user import User
from app.repositories.personal_book_repository import PersonalBookRepository
from app.schemas.personal_analysis import (
    PersonalAnalysisTaskOut,
    PersonalBookAnalysisOut,
    PersonalChapterAnalysisOut,
)
from app.services.personal_analysis_runner import (
    mark_stale_running_failed,
    schedule_analysis,
)


# ================= Service =================


class PersonalAnalysisService:
    """个人书籍分析任务管理：创建/状态/报告/章节结果/取消"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.settings = get_settings()

    # ---------- 归属守卫 ----------

    async def _get_owned_book(self, user: User, personal_book_id: int) -> PersonalBook:
        book = await PersonalBookRepository(db=self.db).get_owned(
            personal_book_id, user.id
        )
        if book is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "个人书籍不存在或无权访问")
        return book

    async def _get_owned_task(self, user: User, personal_book_id: int) -> PersonalAnalysisTask:
        await self._get_owned_book(user, personal_book_id)
        task = (
            await self.db.execute(
                select(PersonalAnalysisTask)
                .where(
                    PersonalAnalysisTask.personal_book_id == personal_book_id,
                    PersonalAnalysisTask.user_id == user.id,
                )
                .order_by(PersonalAnalysisTask.id.desc())
            )
        ).scalars().first()
        if task is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "该书籍尚无分析任务")
        return task

    # ---------- 创建 / 重新触发 ----------

    async def ensure_task(self, user: User, personal_book_id: int) -> PersonalAnalysisTask:
        """创建或获取分析任务（上传成功后自动调用，也可手动重新触发）。

        - 有进行中任务（pending/running）：直接返回，不做重复创建
        - 已完成：返回已完成任务（需要重新分析属后续功能，不在此处处理）
        - failed / cancelled：重置为 pending 重新调度（续跑，已完成章节自动跳过）
        - 无任务：新建 pending 任务并调度
        """
        book = await self._get_owned_book(user, personal_book_id)
        if book.chapter_count == 0:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "该书没有可分析的章节")

        existing = (
            await self.db.execute(
                select(PersonalAnalysisTask)
                .where(
                    PersonalAnalysisTask.personal_book_id == personal_book_id,
                    PersonalAnalysisTask.user_id == user.id,
                )
                .order_by(PersonalAnalysisTask.id.desc())
            )
        ).scalars().first()

        if existing is not None:
            if existing.status in PersonalAnalysisTask.ACTIVE_STATUSES:
                return existing
            # failed / cancelled → 续跑：重置为 pending（已完成章节按版本跳过）
            existing.status = "pending"
            existing.error_message = None
            existing.completed_at = None
            existing.started_at = None
            try:
                await self.db.commit()
                await self.db.refresh(existing)
            except IntegrityError:
                await self.db.rollback()
            schedule_analysis(existing.id)
            return existing

        task = PersonalAnalysisTask(
            user_id=user.id,
            personal_book_id=personal_book_id,
            status="pending",
            total_chapters=book.chapter_count,
        )
        self.db.add(task)
        try:
            await self.db.commit()
        except IntegrityError:
            # 并发竞态兜底：部分唯一索引拒绝同一本书的第二个进行中任务
            await self.db.rollback()
            task = (
                await self.db.execute(
                    select(PersonalAnalysisTask)
                    .where(
                        PersonalAnalysisTask.personal_book_id == personal_book_id,
                        PersonalAnalysisTask.status.in_(PersonalAnalysisTask.ACTIVE_STATUSES),
                    )
                    .order_by(PersonalAnalysisTask.id.desc())
                )
            ).scalars().first()
            if task is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, "分析任务创建失败，请稍后重试"
                )
            return task
        await self.db.refresh(task)
        schedule_analysis(task.id)
        return task

    # ---------- 查询 ----------

    async def get_status(self, user: User, personal_book_id: int) -> PersonalAnalysisTaskOut:
        """任务状态（含懒惰超时兜底：running 超时视为挂死）"""
        await mark_stale_running_failed()
        return PersonalAnalysisTaskOut.model_validate(
            await self._get_owned_task(user, personal_book_id)
        )

    async def get_report(self, user: User, personal_book_id: int) -> PersonalBookAnalysisOut:
        """全书分析报告（章节分析全部完成后才存在）"""
        await self._get_owned_book(user, personal_book_id)
        report = (
            await self.db.execute(
                select(PersonalBookAnalysis).where(
                    PersonalBookAnalysis.personal_book_id == personal_book_id,
                    PersonalBookAnalysis.user_id == user.id,
                )
            )
        ).scalars().first()
        if report is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, "全书分析报告尚未生成（章节分析完成后再试）"
            )
        return PersonalBookAnalysisOut.model_validate(report)

    async def get_chapter_result(
        self, user: User, personal_book_id: int, chapter_index: int
    ) -> PersonalChapterAnalysisOut:
        """指定章节分析结果"""
        await self._get_owned_book(user, personal_book_id)
        result = (
            await self.db.execute(
                select(PersonalChapterAnalysis).where(
                    PersonalChapterAnalysis.personal_book_id == personal_book_id,
                    PersonalChapterAnalysis.user_id == user.id,
                    PersonalChapterAnalysis.chapter_index == chapter_index,
                )
            )
        ).scalars().first()
        if result is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"第 {chapter_index} 章尚无分析结果"
            )
        return PersonalChapterAnalysisOut.model_validate(result)

    # ---------- 取消 ----------

    async def cancel_task(self, user: User, personal_book_id: int) -> PersonalAnalysisTaskOut:
        """取消进行中的分析任务（已完成/已失败的任务取消无意义，返回 400）"""
        task = await self._get_owned_task(user, personal_book_id)
        if task.status not in PersonalAnalysisTask.ACTIVE_STATUSES:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"任务当前状态为 {task.status}，无需取消",
            )
        task.status = "cancelled"
        task.completed_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(task)
        return PersonalAnalysisTaskOut.model_validate(task)


def get_personal_analysis_service(db: AsyncSession = Depends(get_db)) -> PersonalAnalysisService:
    return PersonalAnalysisService(db)
