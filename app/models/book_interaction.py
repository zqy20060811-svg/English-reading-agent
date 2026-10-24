from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BookInteraction(Base):
    """用户-书籍互动状态表：点赞/收藏的当前状态（一人一书一行），热度评分按激活时间衰减"""

    __tablename__ = "book_interactions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), primary_key=True)
    liked: Mapped[bool] = mapped_column(Boolean, default=False)
    liked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    favorited: Mapped[bool] = mapped_column(Boolean, default=False)
    favorited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
