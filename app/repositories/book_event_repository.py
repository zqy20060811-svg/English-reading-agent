from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book_event import BookEvent


class BookEventRepository:
    """书籍行为事件表数据访问层"""

    # 聚合查询窗口：3 倍半衰期（42 天），更早的事件衰减后权重可忽略
    WINDOW_DAYS = 42

    def __init__(self, db: AsyncSession):
        self.db = db

    async def add(self, book_id: int, user_id: int, event_type: str) -> BookEvent:
        event = BookEvent(book_id=book_id, user_id=user_id, event_type=event_type)
        self.db.add(event)
        await self.db.commit()
        return event

    async def iter_events_since(self, since: datetime) -> list[tuple[int, str, datetime]]:
        """窗口内全部事件 (book_id, event_type, created_at)，供热度重算聚合"""
        result = await self.db.execute(
            select(BookEvent.book_id, BookEvent.event_type, BookEvent.created_at).where(
                BookEvent.created_at >= since
            )
        )
        return list(result.all())
