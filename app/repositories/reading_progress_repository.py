from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
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

    async def list_book_ids(self, user_id: int) -> list[int]:
        """用户读过的全部书籍 id（有阅读进度即视为读过）"""
        result = await self.db.execute(
            select(UserReadingProgress.book_id).where(UserReadingProgress.user_id == user_id)
        )
        return list(result.scalars().all())

    async def upsert(
        self, user_id: int, book_id: int, chapter_index: int,
        char_offset: int, percent: float, page_index: int = 0,
    ) -> UserReadingProgress:
        """每人每书一行，存在则更新，不存在则插入（原子 upsert，并发保存安全）"""
        stmt = (
            pg_insert(UserReadingProgress)
            .values(
                user_id=user_id,
                book_id=book_id,
                chapter_index=chapter_index,
                char_offset=char_offset,
                page_index=page_index,
                percent=percent,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "book_id"],
                set_={
                    "chapter_index": chapter_index,
                    "char_offset": char_offset,
                    "page_index": page_index,
                    "percent": percent,
                },
            )
            .returning(UserReadingProgress)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one()
        await self.db.commit()
        return row
