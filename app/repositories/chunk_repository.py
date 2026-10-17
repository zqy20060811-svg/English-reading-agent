"""文本块检索数据访问层：pgvector 余弦相似度 + PostgreSQL 全文检索（ts_rank 关键词路）。

注意：排序用的是 PostgreSQL 全文检索的 ts_rank，并非经典 BM25 算法
（无 IDF、无文档长度归一化）。关键词召回 + 相关性排序对本项目当前规模已够用。
"""

from dataclasses import dataclass

from sqlalchemy import select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book  # noqa: F401 确保外键表注册
from app.models.book_chunk import BookChunk


@dataclass
class ChunkHit:
    """检索单条命中结果（向量路与关键词路共用）"""

    chunk_id: int
    book_id: int
    chapter_id: int
    chunk_index: int
    chunk_text: str
    distance: float | None = None   # 向量余弦距离，越小越相似（语义路）
    bm25_rank: float | None = None  # 全文检索 ts_rank 关键词得分，越大越相关（关键词路；非经典 BM25）


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

        - query_embedding: 查询向量（1024 维，与块向量同一模型生成）
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

    async def search_fulltext(
        self,
        query: str,
        book_id: int | None = None,
        chapter_id: int | None = None,
        top_k: int = 5,
    ) -> list[ChunkHit]:
        """关键词全文检索路（ts_rank 排序，走 to_tsvector('english') 表达式 GIN 索引）。

        - query 先分词为词元再以 OR（|）组合成 tsquery：自然语言问句的实词很少
          同时出现在同一个块里，AND 语义（plainto_tsquery）会导致关键词路几乎
          全部空转（实测 21 题仅 1 题命中）；OR 语义 + ts_rank 排序下，匹配词
          越多的块自然排前。词元由 to_tsvector('english', query) 生成（自动去
          停用词），纯中文查询分不出英文词元时返回空，由向量路兜底（属预期）
        """
        # 参数化 SQL：表达式 GIN 索引要求查询与索引用完全相同的 tsvector 表达式；
        # 词元逐个加双引号防 tsquery 语法注入
        sql = """
            WITH q AS (
                SELECT to_tsquery('english',
                    (SELECT string_agg('"' || replace(lexeme, '"', '""') || '"', ' | ')
                     FROM (SELECT DISTINCT lexeme FROM unnest(to_tsvector('english', :qs))) t)
                ) AS tsq
            )
            SELECT bc.id, bc.book_id, bc.chapter_id, bc.chunk_index, bc.chunk_text,
                   ts_rank(to_tsvector('english', bc.chunk_text), q.tsq) AS rank
            FROM book_chunks bc, q
            WHERE q.tsq IS NOT NULL
              AND to_tsvector('english', bc.chunk_text) @@ q.tsq
            """
        if book_id is not None:
            sql += " AND bc.book_id = :book_id"
        if chapter_id is not None:
            sql += " AND bc.chapter_id = :chapter_id"
        sql += " ORDER BY rank DESC LIMIT :top_k"
        sql = sql_text(sql)

        params = {"qs": query, "top_k": top_k}
        if book_id is not None:
            params["book_id"] = book_id
        if chapter_id is not None:
            params["chapter_id"] = chapter_id

        result = await self.db.execute(sql, params)
        return [
            ChunkHit(
                chunk_id=r.id,
                book_id=r.book_id,
                chapter_id=r.chapter_id,
                chunk_index=r.chunk_index,
                chunk_text=r.chunk_text,
                bm25_rank=float(r.rank),
            )
            for r in result.all()
        ]
