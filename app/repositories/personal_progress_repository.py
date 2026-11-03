"""个人书籍阅读进度数据访问层（每人每本个人书一行，原子 upsert）。"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.personal_reading_progress import PersonalReadingProgress


class PersonalProgressRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_id: int, personal_book_id: int) -> PersonalReadingProgress | None:
        result = await self.db.execute(
            select(PersonalReadingProgress).where(
                PersonalReadingProgress.user_id == user_id,
                PersonalReadingProgress.personal_book_id == personal_book_id,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self, user_id: int, personal_book_id: int, chapter_index: int,
        char_offset: int, percent: float, page_index: int = 0,
    ) -> PersonalReadingProgress:
        stmt = (
            pg_insert(PersonalReadingProgress)
            .values(
                user_id=user_id,
                personal_book_id=personal_book_id,
                chapter_index=chapter_index,
                char_offset=char_offset,
                page_index=page_index,
                percent=percent,
            )
            .on_conflict_do_update(
                index_elements=["user_id", "personal_book_id"],
                set_={
                    "chapter_index": chapter_index,
                    "char_offset": char_offset,
                    "page_index": page_index,
                    "percent": percent,
                },
            )
            .returning(PersonalReadingProgress)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one()
        await self.db.commit()
        return row
