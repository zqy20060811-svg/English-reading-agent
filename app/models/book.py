from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class Book(Base):
    """书籍表：仅存书籍信息与简介，正文内容不存库（正文存于 data/books 目录）"""

    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    gutenberg_id: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    title: Mapped[str] = mapped_column(String(255), index=True)
    author: Mapped[str] = mapped_column(String(255))
    year: Mapped[int] = mapped_column(Integer)
    genre: Mapped[str] = mapped_column(String(50))
    synopsis: Mapped[str] = mapped_column(Text)  # 英文简介
    cover_url: Mapped[str | None] = mapped_column(String(512), nullable=True)  # 封面图（Open Library）
    language: Mapped[str] = mapped_column(String(10), default="en")
    source_url: Mapped[str] = mapped_column(String(512))
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
