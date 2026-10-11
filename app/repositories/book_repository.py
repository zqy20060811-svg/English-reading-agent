from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book


class BookRepository:
    """书籍表数据访问层"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_gutenberg_id(self, gutenberg_id: int) -> Book | None:
        result = await self.db.execute(
            select(Book).where(Book.gutenberg_id == gutenberg_id)
        )
        return result.scalar_one_or_none()

    async def search_by_title(self, title: str) -> list[Book]:
        """按书名模糊查询（大小写不敏感），完全匹配的排在最前。"""
        pattern = f"%{title}%"
        result = await self.db.execute(
            select(Book)
            .where(Book.title.ilike(pattern))
            # 完全匹配（忽略大小写）优先，其余按书名排序
            .order_by(
                func.lower(Book.title) != title.lower(),
                Book.title,
            )
        )
        return list(result.scalars().all())

    async def create(self, book: Book) -> Book:
        self.db.add(book)
        await self.db.commit()
        await self.db.refresh(book)
        return book

    async def update(self, book: Book, **fields) -> Book:
        for key, value in fields.items():
            setattr(book, key, value)
        await self.db.commit()
        await self.db.refresh(book)
        return book
