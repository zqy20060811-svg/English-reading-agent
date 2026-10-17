"""RAG 检索业务逻辑：混合检索（向量路 + PostgreSQL 全文检索 ts_rank 关键词路）→ RRF 融合 → 整理上下文。

两路得分量纲不同（余弦距离 vs ts_rank），不直接相加，
用 Reciprocal Rank Fusion（倒数排名融合）按排名合并候选。
"""

import asyncio
from dataclasses import dataclass

from fastapi import Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.embedding import encode_query
from app.repositories.chunk_repository import ChunkHit, ChunkRepository

TOP_K = 5  # 默认返回条数
RRF_K = 60  # RRF 常数：越大排名差距影响越平滑，业界默认 60
CANDIDATE_K = 10  # 每路召回的候选条数（融合前取宽，融合后取 top_k）


@dataclass
class RetrievalResult:
    """一次检索的结果集与拼装好的上下文"""

    hits: list[ChunkHit]
    context: str  # 拼装后可直接注入 prompt 的证据文本
    query: str


def rrf_fuse(
    result_lists: list[list[ChunkHit]],
    top_k: int = TOP_K,
    weights: list[float] | tuple[float, ...] | None = None,
) -> list[ChunkHit]:
    """加权倒数排名融合：score(chunk) = Σ w_i / (RRF_K + rank_i)，rank 从 1 起。

    - 只看排名不看原始分，天然规避两路量纲不可比的问题
    - weights 与 result_lists 一一对应；None 时全部权重 1.0
    - 同一块被多路同时命中时得分叠加，天然排前
    - 融合后的 ChunkHit 保留各路原始分数（便于调试），顺序即融合排名
    """
    if weights is None:
        weights = [1.0] * len(result_lists)
    assert len(weights) == len(result_lists), "权重数量须与结果列表一致"
    scores: dict[int, float] = {}
    hits: dict[int, ChunkHit] = {}
    for weight, results in zip(weights, result_lists):
        for rank, hit in enumerate(results, 1):
            scores[hit.chunk_id] = scores.get(hit.chunk_id, 0.0) + weight / (RRF_K + rank)
            if hit.chunk_id not in hits:
                hits[hit.chunk_id] = hit
            else:  # 合并两路的原始分数信息
                merged = hits[hit.chunk_id]
                hits[hit.chunk_id] = ChunkHit(
                    chunk_id=merged.chunk_id,
                    book_id=merged.book_id or hit.book_id,
                    chapter_id=merged.chapter_id or hit.chapter_id,
                    chunk_index=merged.chunk_index,
                    chunk_text=merged.chunk_text or hit.chunk_text,
                    distance=merged.distance if merged.distance is not None else hit.distance,
                    bm25_rank=merged.bm25_rank if merged.bm25_rank is not None else hit.bm25_rank,
                )
    ranked_ids = sorted(scores, key=lambda cid: scores[cid], reverse=True)[:top_k]
    return [hits[cid] for cid in ranked_ids]


class RetrievalService:
    """RAG 混合检索服务"""

    def __init__(self, db: AsyncSession):
        self.chunk_repo = ChunkRepository(db)

    async def retrieve_for_question(
        self,
        question: str,
        book_id: int | None = None,
        chapter_id: int | None = None,
        top_k: int = TOP_K,
    ) -> RetrievalResult:
        """混合检索：向量路（语义）+ 全文路（关键词）并行召回，RRF 融合取 Top-K。

        - encode 为 CPU 推理，放入线程池避免阻塞事件循环
        - book_id / chapter_id 为可选过滤（两路同时应用）
        - 纯中文问题时全文路通常为空，融合结果即纯向量结果（向量路兜底）
        """
        vector, ft_hits = await asyncio.gather(
            run_in_threadpool(encode_query, question),
            self.chunk_repo.search_fulltext(
                question, book_id=book_id, chapter_id=chapter_id, top_k=CANDIDATE_K
            ),
        )
        vec_hits = await self.chunk_repo.search(
            vector, book_id=book_id, chapter_id=chapter_id, top_k=CANDIDATE_K
        )
        fused = rrf_fuse([vec_hits, ft_hits], top_k=top_k)
        return RetrievalResult(hits=fused, context=self.format_context(fused), query=question)

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
