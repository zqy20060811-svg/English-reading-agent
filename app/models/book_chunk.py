from sqlalchemy import Column, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.db.database import Base


class BookChunk(Base):
    """文本块表：章节正文递归字符分块后的语义块，用于 RAG 向量检索。

    embedding 模型：BAAI/bge-m3（1024 维，中英文）；
    分块参数：chunk_size=800 字符、overlap=100 字符。
    """

    __tablename__ = "book_chunks"
    __table_args__ = (
        UniqueConstraint("chapter_id", "chunk_index"),
        # 全文检索（ts_rank）关键词路的表达式 GIN 索引（表达式必须与查询中的完全一致才能命中索引）
        Index(
            "ix_book_chunks_fts",
            text("to_tsvector('english', chunk_text)"),
            postgresql_using="gin",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)  # 冗余书籍 ID，便于按书过滤
    chapter_id: Mapped[int] = mapped_column(ForeignKey("book_chapters.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)  # 章内块序号，从 0 开始
    chunk_text: Mapped[str] = mapped_column(Text)  # 原文逐字片段
    embedding = Column(Vector(1024), nullable=True)  # BAAI/bge-m3 输出维度 1024（中英文）
