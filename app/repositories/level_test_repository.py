import math

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.level_test_result import LevelTestResult


class BookDifficultyRow:
    """书目难度聚合行（books LEFT JOIN book_chapters 的平均章节词数）"""

    def __init__(self, book_id: int, title: str, author: str, avg_chapter_words: float):
        self.book_id = book_id
        self.title = title
        self.author = author
        self.avg_chapter_words = round(float(avg_chapter_words), 1)


class LevelTestRepository:
    """英语水平测试结果数据访问层"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save(self, result: LevelTestResult) -> LevelTestResult:
        self.db.add(result)
        await self.db.commit()
        await self.db.refresh(result)
        return result

    async def get_latest(self, user_id: int) -> LevelTestResult | None:
        """最近一次测试结果（保留历史，但查询只取最新）"""
        result = await self.db.execute(
            select(LevelTestResult)
            .where(LevelTestResult.user_id == user_id)
            .order_by(LevelTestResult.created_at.desc(), LevelTestResult.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_history(self, user_id: int, limit: int = 10) -> list[LevelTestResult]:
        result = await self.db.execute(
            select(LevelTestResult)
            .where(LevelTestResult.user_id == user_id)
            .order_by(LevelTestResult.created_at.desc(), LevelTestResult.id.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def books_by_difficulty(self) -> list[BookDifficultyRow]:
        """全部书目按平均章节词数升序（无章节的书排最后）"""
        from app.models.book import Book
        from app.models.book_chapter import BookChapter

        stmt = (
            select(
                Book.id,
                Book.title,
                Book.author,
                func.coalesce(func.avg(BookChapter.word_count), math.inf).label("avg_words"),
            )
            .join(BookChapter, BookChapter.book_id == Book.id, isouter=True)
            .group_by(Book.id, Book.title, Book.author)
            .order_by(func.avg(BookChapter.word_count).asc().nulls_last())
        )
        rows = (await self.db.execute(stmt)).all()
        return [BookDifficultyRow(r[0], r[1], r[2], r[3]) for r in rows]
