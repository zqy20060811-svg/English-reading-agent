from sqlalchemy import Column, ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from pgvector.sqlalchemy import Vector

from app.db.database import Base


class BookChunk(Base):
    """文本块表：章节正文切分后的语义块，用于后续 RAG 向量检索。

    注意：embedding 维度与所选 embedding 模型必须一致，当前按 bge-m3 预留 1024 维。
    向量数据后续再生成写入，建表阶段 embedding 允许为空。
    """

    __tablename__ = "book_chunks"
    __table_args__ = (UniqueConstraint("chapter_id", "chunk_index"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"), index=True)  # 冗余书籍 ID，便于按书过滤
    chapter_id: Mapped[int] = mapped_column(ForeignKey("book_chapters.id"), index=True)
    chunk_index: Mapped[int] = mapped_column(Integer)  # 章内块序号，从 0 开始
    chunk_text: Mapped[str] = mapped_column(Text)  # 原文逐字片段
    embedding = Column(Vector(1024), nullable=True)  # 文本块向量，后续填充
