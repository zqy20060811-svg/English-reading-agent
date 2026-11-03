from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class PersonalBook(Base):
    """个人书籍表：用户上传的私人阅读材料。

    与公共书库（books/book_chapters/book_chunks）完全隔离：
    独立表、独立 ID 空间，任何查询都必须带 user_id 归属校验。
    原始文件保留在磁盘（storage_path），便于后续重新解析。
    """

    __tablename__ = "personal_books"
    __table_args__ = (
        # 同一用户上传同一文件（内容哈希相同）只保留一条，避免重复占用空间
        UniqueConstraint("user_id", "content_sha256", name="uq_personal_book_user_hash"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    author: Mapped[str] = mapped_column(String(255), default="未知作者")
    language: Mapped[str] = mapped_column(String(16), default="en")
    source_type: Mapped[str] = mapped_column(String(8))  # epub / txt（按文件内容判定）
    original_filename: Mapped[str] = mapped_column(String(255))  # 仅展示用，不用于磁盘路径
    file_size: Mapped[int] = mapped_column(Integer, default=0)  # 字节
    content_sha256: Mapped[str] = mapped_column(String(64))     # 内容哈希，用于去重
    storage_path: Mapped[str] = mapped_column(String(512))      # 原始文件磁盘路径
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    chapter_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
