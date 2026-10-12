from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class UserReadingProgress(Base):
    """阅读进度表：每人每书一行，upsert 更新"""

    __tablename__ = "user_reading_progress"
    __table_args__ = (UniqueConstraint("user_id", "book_id"),)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), primary_key=True
    )
    book_id: Mapped[int] = mapped_column(
        ForeignKey("books.id"), primary_key=True
    )
    chapter_index: Mapped[int] = mapped_column(Integer, default=1)  # 读到第几章
    char_offset: Mapped[int] = mapped_column(Integer, default=0)  # 章内字符偏移
    percent: Mapped[float] = mapped_column(Float, default=0.0)  # 全书阅读百分比
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
