"""书签数据访问层"""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_bookmark import UserBookmark


class BookmarkRepository:
    """书签表数据访问层"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_user(
        self, user_id: int, book_id: int | None = None
    ) -> list[UserBookmark]:
        """用户书签列表，可按书过滤，按创建时间倒序"""
        stmt = select(UserBookmark).where(UserBookmark.user_id == user_id)
        if book_id is not None:
            stmt = stmt.where(UserBookmark.book_id == book_id)
        result = await self.db.execute(stmt.order_by(UserBookmark.created_at.desc()))
        return list(result.scalars().all())

    async def get_by_position(
        self, user_id: int, book_id: int, chapter_index: int, page_index: int
    ) -> UserBookmark | None:
        result = await self.db.execute(
            select(UserBookmark).where(
                UserBookmark.user_id == user_id,
                UserBookmark.book_id == book_id,
                UserBookmark.chapter_index == chapter_index,
                UserBookmark.page_index == page_index,
            )
        )
        return result.scalar_one_or_none()

    async def add(
        self, user_id: int, book_id: int, chapter_index: int,
        page_index: int, excerpt: str,
    ) -> UserBookmark:
        """添加书签（原子插入：并发重复添加由唯一约束兜底，冲突返回已有条目）"""
        stmt = (
            pg_insert(UserBookmark)
            .values(
                user_id=user_id,
                book_id=book_id,
                chapter_index=chapter_index,
                page_index=page_index,
                excerpt=excerpt,
            )
            .on_conflict_do_nothing(
                index_elements=["user_id", "book_id", "chapter_index", "page_index"]
            )
            .returning(UserBookmark)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        await self.db.commit()
        if row is not None:
            return row
        return await self.get_by_position(user_id, book_id, chapter_index, page_index)

    async def remove(self, user_id: int, bookmark_id: int) -> int:
        """删除书签，返回删除行数（0 表示不存在）"""
        result = await self.db.execute(
            delete(UserBookmark).where(
                UserBookmark.user_id == user_id,
                UserBookmark.id == bookmark_id,
            )
        )
        await self.db.commit()
        return result.rowcount or 0
