from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class UserVocabulary(Base):
    """生词本表：用户收藏的生词，每用户每词唯一（跨书去重）"""

    __tablename__ = "user_vocabulary"
    __table_args__ = (
        UniqueConstraint("user_id", "word", name="uq_vocabulary_user_word"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), index=True
    )
    book_id: Mapped[int | None] = mapped_column(
        ForeignKey("books.id"), index=True
    )  # 首次收录时所在的书；个人书籍收录时为 NULL（个人书不在公共 books 表）
    word: Mapped[str] = mapped_column(String(64), index=True)  # 归一化小写
    # 收录时的上下文例句（可选，便于回忆词义场景）
    context_sentence: Mapped[str | None] = mapped_column(Text, nullable=True)
    chapter_index: Mapped[int] = mapped_column(Integer, default=1)  # 收录时所在章节
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
