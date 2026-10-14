from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.reading_progress import UserReadingProgress


class ReadingProgressRepository:
    """阅读进度表数据访问层"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: int, book_id: int) -> UserReadingProgress | None:
        result = await self.db.execute(
            select(UserReadingProgress).where(
                UserReadingProgress.user_id == user_id,
                UserReadingProgress.book_id == book_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, user_id: int, book_id: int, chapter_index: int, char_offset: int, percent: float
    ) -> UserReadingProgress:
        """每人每书一行，存在则更新，不存在则插入"""
        row = await self.get(user_id, book_id)
        if row is None:
            row = UserReadingProgress(
                user_id=user_id,
                book_id=book_id,
                chapter_index=chapter_index,
                char_offset=char_offset,
                percent=percent,
            )
            self.db.add(row)
        else:
            row.chapter_index = chapter_index
            row.char_offset = char_offset
            row.percent = percent
        await self.db.commit()
        await self.db.refresh(row)
        return row
