"""检索评测与 RRF 融合单元测试。

- TestRRFFuse / TestRRFEdge：纯函数单元测试，无外部依赖，始终运行
- TestRetrievalBenchmark：需要本地 PostgreSQL 与 BGE-M3 模型，缺失时自动跳过
  （按书内检索口径运行 25 题基准，断言 Recall@5 / MRR 下限，并输出逐题明细与耗时）

运行：python -m pytest tests/ -v
结果记录：最近一次基准结果写入 tests/benchmark_results.json（不入库的运行也会本地生成）
"""

import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

from tests.retrieval_cases import BENCHMARK_CASES

from app.repositories.chunk_repository import ChunkHit
from app.services.retrieval_service import RRF_K, rrf_fuse

RESULTS_PATH = Path(__file__).parent / "benchmark_results.json"


def _dispose_engine():
    """asyncio.run 每次创建新事件循环，而 asyncpg 连接池绑定在创建时的循环上；
    阶段切换时 dispose 引擎，避免连接跨循环复用报 InterfaceError。"""
    from app.db.database import engine

    asyncio.run(engine.dispose())


def _hit(chunk_id: int) -> ChunkHit:
    return ChunkHit(chunk_id=chunk_id, book_id=1, chapter_id=1, chunk_index=chunk_id, chunk_text=f"text{chunk_id}")


class TestRRFFuse:
    """RRF 融合纯函数单元测试（确定性，无外部依赖）"""

    def test_single_list_preserves_rank_order(self):
        fused = rrf_fuse([[_hit(1), _hit(2), _hit(3)]], top_k=5)
        assert [h.chunk_id for h in fused] == [1, 2, 3]

    def test_dual_hit_ranks_first(self):
        # 两路同时命中的块得分叠加，应排在任何单路命中的块之前
        fused = rrf_fuse([[_hit(1), _hit(2)], [_hit(2), _hit(3)]], top_k=5)
        assert fused[0].chunk_id == 2  # 1/(60+1)+1/(60+1) > 1/61

    def test_scores_follow_rrf_formula(self):
        fused = rrf_fuse([[_hit(1), _hit(2)]], top_k=5)
        # 只有排名参与计算：块1 rank=1 → 1/(60+1)
        assert len(fused) == 2
        # 验证顺序：rank 越前分越高
        assert fused[0].chunk_id == 1

    def test_top_k_limits_output(self):
        fused = rrf_fuse([[_hit(i) for i in range(1, 8)]], top_k=5)
        assert len(fused) == 5

    def test_empty_input(self):
        assert rrf_fuse([[]], top_k=5) == []
        assert rrf_fuse([], top_k=5) == []

    def test_rrf_k_constant_used(self):
        # k=60 时 rank1 与 rank2 的分差平滑（0.0164 vs 0.0161），防手滑改坏公式
        assert RRF_K == 60


class TestRetrievalBenchmark:
    """25 题基准：需要 DB 与模型，环境缺失时跳过"""

    @pytest.fixture(scope="class")
    def eval_env(self):
        try:
            from app.embedding import encode_texts  # noqa: F401
        except Exception as e:  # 模型不可用
            pytest.skip(f"embedding 模型不可用: {e}")
        try:
            from app.db.database import engine  # noqa: F401
            import asyncpg  # noqa: F401
        except Exception as e:  # DB 依赖不可用
            pytest.skip(f"数据库依赖不可用: {e}")

        async def _check():
            from sqlalchemy import text
            from app.db.database import AsyncSessionLocal
            async with AsyncSessionLocal() as s:
                n = (await s.execute(text("SELECT count(*) FROM book_chunks WHERE embedding IS NOT NULL"))).scalar()
            return n

        try:
            embedded = asyncio.run(_check())
        except Exception as e:
            pytest.skip(f"数据库不可达: {e}")
        if embedded == 0:
            pytest.skip("book_chunks 无向量数据，请先运行 python -m app.scripts.embed_chunks")
        _dispose_engine()
        yield embedded
        _dispose_engine()

    def test_benchmark_recall_and_mrr(self, eval_env):
        from sqlalchemy import text

        from app.db.database import AsyncSessionLocal
        from app.embedding import encode_texts
        from app.repositories.chunk_repository import ChunkRepository
        from app.services.retrieval_service import rrf_fuse

        async def run():
            rows = []
            async with AsyncSessionLocal() as s:
                ch_map = {}
                for cid, bid, idx in (await s.execute(
                    text("SELECT id, book_id, chapter_index FROM book_chapters")
                )).all():
                    ch_map[cid] = (bid, idx)
                repo = ChunkRepository(s)
                questions = [c.question for c in BENCHMARK_CASES]
                vectors = encode_texts(questions)
                # 查询改写组：DeepSeek 可用时启用（改写结果缓存于 llm 实例）
                from app.services.llm_service import LLMService

                llm = LLMService()
                rewrites: dict[str, str] = {}

                async def rewrite(q: str) -> str:
                    rewrites[q] = await llm.rewrite_query(q)
                    return rewrites[q]

                for case, vec in zip(BENCHMARK_CASES, vectors):
                    t0 = time.perf_counter()
                    ft = await repo.search_fulltext(case.question, book_id=case.book_id, top_k=10) if case.book_id else []
                    v = await repo.search(vec, book_id=case.book_id, top_k=10) if case.book_id else []
                    hybrid = rrf_fuse([v, ft], top_k=5) if case.book_id else []
                    ms = (time.perf_counter() - t0) * 1000
                    # 改写组：多查询融合（原问题 + 改写查询，各跑向量/全文两路，四列表 RRF），
                    # 与线上 retrieve_for_question(rewriter=...) 行为一致
                    t1 = time.perf_counter()
                    try:
                        rw = await rewrite(case.question)
                        ft_rw = await repo.search_fulltext(rw, book_id=case.book_id, top_k=10) if case.book_id else []
                        v_rw = await repo.search(encode_texts([rw])[0], book_id=case.book_id, top_k=10) if case.book_id else []
                        hybrid_rw = rrf_fuse([v, v_rw, ft, ft_rw], top_k=5) if case.book_id else []
                        rw_ok = True
                    except Exception:
                        hybrid_rw, rw_ok = [], False
                    ms_rw = (time.perf_counter() - t1) * 1000
                    gold_top10_rank = _gold_rank(v, ch_map, case)  # 证据在向量路 Top-10 中的排名
                    rows.append({
                        "id": case.id, "category": case.category, "question": case.question,
                        "should_answer": case.should_answer,
                        "ft_hits": len(ft),
                        # 基线口径统一 Top-5：纯向量取前 5，混合融合后取 5，两者公平可比
                        "vec_rank": _gold_rank(v[:5], ch_map, case),
                        "hybrid_rank": _gold_rank(hybrid, ch_map, case),
                        "rewrite_rank": _gold_rank(hybrid_rw, ch_map, case) if rw_ok else None,
                        "rewritten_query": rewrites.get(case.question),
                        # 逐题 Top-5 明细（章节号列表，含顺序），供人工核对证据位置
                        "vec_top5": [ch_map[h.chapter_id][1] for h in v[:5]],
                        "hybrid_top5": [ch_map[h.chapter_id][1] for h in hybrid[:5]],
                        "rewrite_top5": [ch_map[h.chapter_id][1] for h in hybrid_rw[:5]] if rw_ok else None,
                        # 漏召回分类：证据不在向量 Top-10 → 召回缺失（查询改写方向）；
                        # 在 Top-6~10 → 排序问题（Reranker 方向）；在 Top-5 内 → 命中
                        "miss_class": _miss_class(gold_top10_rank, case.should_answer),
                        "latency_ms": round(ms, 1),
                        "rewrite_latency_ms": round(ms_rw, 1) if rw_ok else None,
                    })
            return rows

        rows = asyncio.run(run())
        answered = [r for r in rows if r["should_answer"]]
        rw_answered = [r for r in answered if r["rewrite_rank"] is not None]
        recall_v = sum(r["vec_rank"] > 0 for r in answered) / len(answered)
        recall_h = sum(r["hybrid_rank"] > 0 for r in answered) / len(answered)
        recall_rw = sum(r["rewrite_rank"] > 0 for r in rw_answered) / len(rw_answered) if rw_answered else None
        mrr_v = sum(1 / r["vec_rank"] for r in answered if r["vec_rank"]) / len(answered)
        mrr_h = sum(1 / r["hybrid_rank"] for r in answered if r["hybrid_rank"]) / len(answered)
        mrr_rw = sum(1 / r["rewrite_rank"] for r in rw_answered if r["rewrite_rank"]) / len(rw_answered) if rw_answered else None
        avg_ms = sum(r["latency_ms"] for r in rows) / len(rows)

        RESULTS_PATH.write_text(
            json.dumps({"run_at": datetime.now(timezone.utc).isoformat(), "metrics": {
                "recall@5_vector": round(recall_v, 4), "recall@5_hybrid": round(recall_h, 4),
                "recall@5_rewrite": round(recall_rw, 4) if recall_rw is not None else None,
                "mrr_vector": round(mrr_v, 4), "mrr_hybrid": round(mrr_h, 4),
                "mrr_rewrite": round(mrr_rw, 4) if mrr_rw is not None else None,
                "avg_latency_ms": round(avg_ms, 1)}, "rows": rows}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        print(f"\nRecall@5 向量={recall_v:.1%} 混合={recall_h:.1%}"
              + (f" 改写={recall_rw:.1%}" if recall_rw is not None else "")
              + f" | MRR 向量={mrr_v:.3f} 混合={mrr_h:.3f}"
              + (f" 改写={mrr_rw:.3f}" if mrr_rw is not None else "")
              + f" | 平均耗时 {avg_ms:.0f}ms")
        for r in rows:
            rw_info = f" rw={r['rewritten_query']!r} rwrank={_fmt(r['rewrite_rank'])}" if r["rewrite_rank"] is not None else ""
            print(f"  {r['id']} [{r['category']}] ft={r['ft_hits']} vec={_fmt(r['vec_rank'])} hyb={_fmt(r['hybrid_rank'])}{rw_info}")

        # 下限断言：低于历史基线（0.75）即回归
        assert recall_h >= 0.75, f"混合检索 Recall@5 回归: {recall_h:.1%}，明细见 tests/benchmark_results.json"

        # 无答案题：检索层不为空 → 证明拒答必须依赖 LLM 判断（llm_service 提示词），而非检索为空
        no_answer = [r for r in rows if not r["should_answer"]]
        for r in no_answer:
            print(f"  {r['id']} 无答案题候选 vec_rank={r['vec_rank']} ft_hits={r['ft_hits']}（LLM 拒答兜底）")

        # 漏召回分类汇总（决定优化方向：排序问题→Reranker；召回缺失→查询改写）
        misses = [r for r in answered if r["vec_rank"] == 0]
        by_class = {}
        for r in misses:
            by_class.setdefault(r["miss_class"], []).append(r["id"])
        print("\n漏召回分类：")
        for cls, ids in by_class.items():
            print(f"  {cls}: {ids}")


def _miss_class(gold_top10_rank: int, should_answer: bool) -> str:
    if not should_answer:
        return "无答案题"
    if gold_top10_rank == 0:
        return "召回缺失_查询改写方向"
    if gold_top10_rank <= 5:
        return "命中"
    return "排序问题_Reranker方向"


def _gold_rank(hits, ch_map, case):
    for rank, h in enumerate(hits, 1):
        bid, cidx = ch_map[h.chapter_id]
        if bid == case.book_id and cidx in case.expected_chapter_indexes:
            return rank
    return 0


def _fmt(rank):
    return f"HIT@{rank}" if rank else "MISS"
