from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class BookChapter(Base):
    """章节表：存储书籍章节原文（正文的唯一存储位置）"""

    __tablename__ = "book_chapters"
    __table_args__ = (UniqueConstraint("book_id", "chapter_index"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)
    chapter_index: Mapped[int] = mapped_column(Integer)  # 章节序号，从 1 开始
    title: Mapped[str] = mapped_column(String(255))  # 章节标题，无标题时用 "Chapter N"
    content: Mapped[str] = mapped_column(Text)  # 章节原文
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
