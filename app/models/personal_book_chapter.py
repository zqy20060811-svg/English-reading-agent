from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PersonalBookChapter(Base):
    """个人书籍章节表：用户上传书籍的章节正文（与公共 book_chapters 完全隔离）。

    删除个人书籍时随外键 CASCADE 一并清理。
    """

    __tablename__ = "personal_book_chapters"
    __table_args__ = (
        UniqueConstraint("personal_book_id", "chapter_index", name="uq_personal_chapter_index"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    personal_book_id: Mapped[int] = mapped_column(
        ForeignKey("personal_books.id", ondelete="CASCADE"), index=True
    )
    chapter_index: Mapped[int] = mapped_column(Integer)  # 从 1 开始
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
