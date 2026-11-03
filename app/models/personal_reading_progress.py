from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PersonalReadingProgress(Base):
    """个人书籍阅读进度：每人每本个人书一行（与公共阅读进度表物理隔离）。

    删除个人书籍时随外键 CASCADE 一并清理。
    """

    __tablename__ = "personal_reading_progress"
    __table_args__ = (
        UniqueConstraint("user_id", "personal_book_id", name="uq_personal_progress_user_book"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    personal_book_id: Mapped[int] = mapped_column(
        ForeignKey("personal_books.id", ondelete="CASCADE"), index=True
    )
    chapter_index: Mapped[int] = mapped_column(Integer, default=1)
    char_offset: Mapped[int] = mapped_column(Integer, default=0)
    page_index: Mapped[int] = mapped_column(Integer, default=0)
    percent: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
