"""文本块向量检索数据访问层：pgvector 余弦相似度查询。"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book  # noqa: F401 确保外键表注册
from app.models.book_chunk import BookChunk


@dataclass
class ChunkHit:
    """向量检索单条命中结果"""

    chunk_id: int
    book_id: int
    chapter_id: int
    chunk_index: int
    chunk_text: str
    distance: float  # 余弦距离，越小越相似


class ChunkRepository:
    """book_chunks 表向量检索"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def search(
        self,
        query_embedding: list[float],
        book_id: int | None = None,
        chapter_id: int | None = None,
        top_k: int = 5,
    ) -> list[ChunkHit]:
        """按余弦距离检索最相似的文本块。

        - query_embedding: 查询向量（384 维，与块向量同一模型生成）
        - book_id / chapter_id: 可选过滤条件（二者可同时使用）
        - top_k: 返回条数，默认 5
        """
        distance = BookChunk.embedding.cosine_distance(query_embedding)
        stmt = (
            select(
                BookChunk.id,
                BookChunk.book_id,
                BookChunk.chapter_id,
                BookChunk.chunk_index,
                BookChunk.chunk_text,
                distance.label("distance"),
            )
            .where(BookChunk.embedding.is_not(None))
            .order_by(distance)
            .limit(top_k)
        )
        if book_id is not None:
            stmt = stmt.where(BookChunk.book_id == book_id)
        if chapter_id is not None:
            stmt = stmt.where(BookChunk.chapter_id == chapter_id)

        result = await self.db.execute(stmt)
        return [
            ChunkHit(
                chunk_id=r.id,
                book_id=r.book_id,
                chapter_id=r.chapter_id,
                chunk_index=r.chunk_index,
                chunk_text=r.chunk_text,
                distance=float(r.distance),
            )
            for r in result.all()
        ]

    async def get_chunks_by_chapter(self, chapter_id: int) -> list[BookChunk]:
        """取某章节全部块（按块序号升序），供拼接完整章节上下文使用"""
        result = await self.db.execute(
            select(BookChunk)
            .where(BookChunk.chapter_id == chapter_id)
            .order_by(BookChunk.chunk_index)
        )
        return list(result.scalars().all())
