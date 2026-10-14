from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book_chapter import BookChapter


class ChapterRepository:
    """章节表数据访问层"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_book(self, book_id: int) -> list[BookChapter]:
        """按章节序号升序返回某书的章节（目录场景不取 content 大字段）"""
        result = await self.db.execute(
            select(
                BookChapter.id,
                BookChapter.chapter_index,
                BookChapter.title,
                BookChapter.word_count,
            )
            .where(BookChapter.book_id == book_id)
            .order_by(BookChapter.chapter_index)
        )
        return [
            BookChapter(id=r.id, chapter_index=r.chapter_index, title=r.title, word_count=r.word_count)
            for r in result.all()
        ]

    async def get_by_book_and_index(self, book_id: int, chapter_index: int) -> BookChapter | None:
        """取指定章节（含正文）"""
        result = await self.db.execute(
            select(BookChapter)
            .where(BookChapter.book_id == book_id, BookChapter.chapter_index == chapter_index)
        )
        return result.scalar_one_or_none()

