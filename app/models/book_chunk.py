from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.db.database import Base


class BookChunk(Base):
    """文本块表：章节正文递归字符分块后的语义块，用于 RAG 向量检索。

    embedding 模型：BAAI/bge-m3（1024 维，中英文）；
    分块参数：chunk_size=800 字符、overlap=100 字符。
    """

    __tablename__ = "book_chunks"
    __table_args__ = (UniqueConstraint("chapter_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)  # 冗余书籍 ID，便于按书过滤
    chapter_id: Mapped[int] = mapped_column(ForeignKey("book_chapters.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)  # 章内块序号，从 0 开始
    chunk_text: Mapped[str] = mapped_column(Text)  # 原文逐字片段
    embedding = Column(Vector(1024), nullable=True)  # BAAI/bge-m3 输出维度 1024（中英文）
