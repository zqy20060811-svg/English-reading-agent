from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class UserBookmark(Base):
    """书签表：用户在阅读过程中收藏的位置，每用户每书每章每页唯一"""

    __tablename__ = "user_bookmarks"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "book_id", "chapter_index", "page_index",
            name="uq_bookmark_user_book_chapter_page",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    chapter_index: Mapped[int] = mapped_column(Integer)  # 书签所在章节
    page_index: Mapped[int] = mapped_column(Integer, default=0)  # 章内页码（0 起）
    # 书签所在页的摘要（展示用，便于识别书签位置）
    excerpt: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
