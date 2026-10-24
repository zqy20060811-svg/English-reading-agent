from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book_interaction import BookInteraction

# kind 参数与字段的映射（like -> liked/liked_at，favorite -> favorited/favorited_at）
_KIND_FIELD = {
    "like": ("liked", "liked_at"),
    "favorite": ("favorited", "favorited_at"),
}


class BookInteractionRepository:
    """点赞/收藏互动状态表数据访问层"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, book_id: int, user_id: int) -> BookInteraction | None:
        result = await self.db.execute(
            select(BookInteraction).where(
                BookInteraction.book_id == book_id,
                BookInteraction.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def toggle(self, book_id: int, user_id: int, kind: str) -> bool:
        """切换点赞/收藏状态，返回切换后的状态（True=激活）"""
        row = await self.get(book_id, user_id)
        if row is None:
            row = BookInteraction(book_id=book_id, user_id=user_id)
            self.db.add(row)
        field, ts_field = _KIND_FIELD[kind]
        active = not getattr(row, field)
        setattr(row, field, active)
        setattr(row, ts_field, datetime.now(timezone.utc) if active else None)
        await self.db.commit()
        return active

    async def count_active(self, book_id: int, kind: str) -> int:
        """某本书当前点赞/收藏总数"""
        field, _ = _KIND_FIELD[kind]
        col = getattr(BookInteraction, field)
        result = await self.db.execute(
            select(func.count())
            .select_from(BookInteraction)
            .where(BookInteraction.book_id == book_id, col.is_(True))
        )
        return result.scalar_one()

    async def list_active_book_ids(self, user_id: int) -> list[int]:
        """用户点赞或收藏过的全部书籍 id"""
        result = await self.db.execute(
            select(BookInteraction.book_id).where(
                BookInteraction.user_id == user_id,
                (BookInteraction.liked.is_(True)) | (BookInteraction.favorited.is_(True)),
            )
        )
        return list(result.scalars().all())

    async def iter_active_since(self, since: datetime, kind: str) -> list[tuple[int, datetime]]:
        """窗口内仍处于激活状态的互动 (book_id, 激活时间)，供热度重算"""
        field, ts_field = _KIND_FIELD[kind]
        col = getattr(BookInteraction, field)
        ts_col = getattr(BookInteraction, ts_field)
        result = await self.db.execute(
            select(BookInteraction.book_id, ts_col).where(
                col.is_(True),
                ts_col >= since,
            )
        )
        return list(result.all())
