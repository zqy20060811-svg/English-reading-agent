"""RAG 检索业务逻辑：用户问题向量化 → pgvector 检索 → 整理上下文。"""

from dataclasses import dataclass

from fastapi import Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.embedding import encode_query
from app.repositories.chunk_repository import ChunkHit, ChunkRepository

TOP_K = 5  # 默认检索条数


@dataclass
class RetrievalResult:
    """一次检索的结果集与拼装好的上下文"""

    hits: list[ChunkHit]
    context: str  # 拼装后可直接注入 prompt 的证据文本
    query: str


class RetrievalService:
    """RAG 检索服务"""

    def __init__(self, db: AsyncSession):
        self.chunk_repo = ChunkRepository(db)

    async def retrieve_for_question(
        self,
        question: str,
        book_id: int | None = None,
        chapter_id: int | None = None,
        top_k: int = TOP_K,
    ) -> RetrievalResult:
        """问题 → 向量 → 余弦相似度检索 Top-K 文本块，并拼装证据上下文。

        - encode 为 CPU 推理，放入线程池避免阻塞事件循环
        - book_id / chapter_id 为可选过滤（如限定在某本书/某一章内检索）
        """
        vector = await run_in_threadpool(encode_query, question)
        hits = await self.chunk_repo.search(vector, book_id=book_id, chapter_id=chapter_id, top_k=top_k)
        return RetrievalResult(hits=hits, context=self.format_context(hits), query=question)

    @staticmethod
    def format_context(hits: list[ChunkHit]) -> str:
        """把命中块拼装为带出处标注的证据文本（供 LLM 引用）。"""
        if not hits:
            return ""
        parts = []
        for i, h in enumerate(hits, 1):
            parts.append(f"[Excerpt {i} | book_id={h.book_id} chapter_id={h.chapter_id} chunk#{h.chunk_index}]\n{h.chunk_text}")
        return "\n\n".join(parts)


def get_retrieval_service(db: AsyncSession = Depends(get_db)) -> RetrievalService:
    return RetrievalService(db)
