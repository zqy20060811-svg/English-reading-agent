"""个人书籍数据访问层：所有查询强制带 user_id 归属条件（隔离的安全边界）。"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.personal_book import PersonalBook
from app.models.personal_book_chapter import PersonalBookChapter


class PersonalBookRepository:
    """个人书籍与章节的数据访问（个人书独立表，与公共书库无交集）"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_user(self, user_id: int) -> list[PersonalBook]:
        result = await self.db.execute(
            select(PersonalBook)
            .where(PersonalBook.user_id == user_id)
            .order_by(PersonalBook.created_at.desc(), PersonalBook.id.desc())
        )
        return list(result.scalars().all())

    async def update_cover_ext(self, book_id: int, cover_ext: str) -> None:
        """回填内嵌封面扩展名（存量书籍惰性迁移用）"""
        result = await self.db.execute(
            select(PersonalBook).where(PersonalBook.id == book_id)
        )
        book = result.scalars().first()
        if book is not None:
            book.cover_ext = cover_ext
            await self.db.flush()

    async def get_owned(self, personal_book_id: int, user_id: int) -> PersonalBook | None:
        """按用户取书：查不到即视为不存在（不区分「他人的书」与「不存在」）"""
        result = await self.db.execute(
            select(PersonalBook).where(
                PersonalBook.id == personal_book_id,
                PersonalBook.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_hash(self, user_id: int, content_sha256: str) -> PersonalBook | None:
        result = await self.db.execute(
            select(PersonalBook).where(
                PersonalBook.user_id == user_id,
                PersonalBook.content_sha256 == content_sha256,
            )
        )
        return result.scalar_one_or_none()

    async def usage(self, user_id: int) -> tuple[int, int]:
        """已用数量与总字节（配额校验用）"""
        result = await self.db.execute(
            select(func.count(), func.coalesce(func.sum(PersonalBook.file_size), 0))
            .where(PersonalBook.user_id == user_id)
        )
        count, total = result.one()
        return int(count), int(total)

    async def create(self, **values) -> PersonalBook:
        book = PersonalBook(**values)
        self.db.add(book)
        await self.db.flush()
        return book

    async def add_chapters(self, book_id: int, chapters: list[tuple[str, str]], word_counts: list[int]):
        self.db.add_all([
            PersonalBookChapter(
                personal_book_id=book_id,
                chapter_index=i,
                title=title[:255],
                content=body,
                word_count=wc,
            )
            for i, ((title, body), wc) in enumerate(zip(chapters, word_counts), start=1)
        ])

    async def list_chapters(self, personal_book_id: int) -> list[PersonalBookChapter]:
        result = await self.db.execute(
            select(PersonalBookChapter)
            .where(PersonalBookChapter.personal_book_id == personal_book_id)
            .order_by(PersonalBookChapter.chapter_index)
        )
        return list(result.scalars().all())

    async def get_chapter(
        self, personal_book_id: int, chapter_index: int
    ) -> PersonalBookChapter | None:
        result = await self.db.execute(
            select(PersonalBookChapter).where(
                PersonalBookChapter.personal_book_id == personal_book_id,
                PersonalBookChapter.chapter_index == chapter_index,
            )
        )
        return result.scalar_one_or_none()

    async def delete(self, book: PersonalBook) -> None:
        """删除书籍：显式清理章节与进度，外键 CASCADE 作为第二道防线"""
        from app.models.personal_reading_progress import PersonalReadingProgress

        await self.db.execute(
            PersonalReadingProgress.__table__.delete().where(
                PersonalReadingProgress.personal_book_id == book.id
            )
        )
        await self.db.execute(
            PersonalBookChapter.__table__.delete().where(
                PersonalBookChapter.personal_book_id == book.id
            )
        )
        await self.db.delete(book)
        await self.db.commit()
