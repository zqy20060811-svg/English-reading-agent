"""新书入库流水线：书籍同步 → 章节切分 → 分块 → 向量化。

供爬虫（--ingest / --embed）与独立脚本复用，各环节带耗时统计。
原始正文始终落盘 data/books/（作为重新切分/重建向量的数据源），本流水线
只负责把磁盘内容推进数据库。
"""
import asyncio
import time

from sqlalchemy import delete, select

from app.chunking import recursive_split
from app.core.redis import get_redis
from app.db.database import AsyncSessionLocal
from app.models.book import Book
from app.models.book_chapter import BookChapter
from app.models.book_chunk import BookChunk
from app.services.book_service import BookService
from app.services.chapter_service import sync_chapters_from_local


async def sync_books() -> object:
    """把 data/books/*/info.json 同步进 books 表（幂等 upsert）。"""
    async with AsyncSessionLocal() as s:
        return await BookService(s).sync_from_crawler()


async def chunk_books(gutenberg_ids: list[int] | None = None) -> dict:
    """按古登堡 ID 重建分块（None 表示全部书），返回统计与各环节耗时。

    注意：传空列表表示「没有书要处理」，直接返回不触碰任何数据；
    只有 None 才代表全库重建（会清空全库向量后重建）。
    """
    t0 = time.perf_counter()
    if gutenberg_ids is not None and not gutenberg_ids:
        return {
            "chapters": 0, "chunks": 0, "split_s": 0.0, "db_s": 0.0,
            "commit_s": 0.0, "total_s": time.perf_counter() - t0,
        }
    async with AsyncSessionLocal() as s:
        # 兜底清理孤儿分块：章节已被删除但其分块（含向量）仍残留的历史数据，
        # 否则会按 book_id 继续命中检索、用旧原文污染 RAG 回答
        orphan_stmt = delete(BookChunk).where(
            BookChunk.chapter_id.not_in(select(BookChapter.id))
        )
        if gutenberg_ids is not None:
            orphan_stmt = orphan_stmt.where(
                BookChunk.book_id.in_(
                    select(Book.id).where(Book.gutenberg_id.in_(gutenberg_ids))
                )
            )
        await s.execute(orphan_stmt)

        stmt = select(BookChapter.id, BookChapter.book_id, BookChapter.content)
        if gutenberg_ids is not None:
            stmt = (
                stmt.where(BookChapter.book_id == Book.id)
                .where(Book.gutenberg_id.in_(gutenberg_ids))
            )
        rows = (await s.execute(stmt)).all()

        t_split = t_db = 0.0
        total = 0
        for chapter_id, book_id, content in rows:
            t1 = time.perf_counter()
            chunks = recursive_split(content)
            t_split += time.perf_counter() - t1

            t1 = time.perf_counter()
            await s.execute(delete(BookChunk).where(BookChunk.chapter_id == chapter_id))
            for idx, chunk_text in enumerate(chunks):
                s.add(
                    BookChunk(
                        book_id=book_id,
                        chapter_id=chapter_id,
                        chunk_index=idx,
                        chunk_text=chunk_text,
                    )
                )
            t_db += time.perf_counter() - t1
            total += len(chunks)

        t1 = time.perf_counter()
        await s.commit()
        t_commit = time.perf_counter() - t1
    return {
        "chapters": len(rows),
        "chunks": total,
        "split_s": t_split,
        "db_s": t_db,
        "commit_s": t_commit,
        "total_s": time.perf_counter() - t0,
    }


async def embed_missing_chunks(
    limit: int | None = None, gutenberg_ids: list[int] | None = None
) -> dict:
    """为 book_chunks 中缺 embedding 的块生成向量（BGE-M3 本地推理）。

    Args:
        limit: 最多处理的块数（调试/分批用）。
        gutenberg_ids: 只处理指定书籍的缺向量块；None 表示全库。
            入库任务应传入本次书号，避免顺带补算全库欠账导致任务时长不可控。
        空列表表示「没有书要处理」，直接返回 0 而不触发全库补算。

    返回处理的块数与耗时拆分：model_s 模型加载、encode_s 编码、db_s 写库。
    app.embedding 延迟导入，避免不向量化时加载 sentence-transformers。
    """
    from app.embedding import encode_texts

    BATCH_SIZE = 32
    if gutenberg_ids is not None and not gutenberg_ids:
        return {"chunks": 0, "model_s": 0.0, "encode_s": 0.0, "db_s": 0.0}
    async with AsyncSessionLocal() as s:
        id_q = select(BookChunk.id).where(BookChunk.embedding.is_(None))
        if gutenberg_ids is not None:
            id_q = id_q.where(
                BookChunk.book_id.in_(
                    select(Book.id).where(Book.gutenberg_id.in_(gutenberg_ids))
                )
            )
        id_q = id_q.order_by(BookChunk.id)  # 确定性顺序：先进先补
        if limit:
            id_q = id_q.limit(limit)
        ids = (await s.execute(id_q)).scalars().all()
        if not ids:
            return {"chunks": 0, "model_s": 0.0, "encode_s": 0.0, "db_s": 0.0}

        # 模型加载单独计时（首次调用 encode_texts 时触发 lru_cache 单例加载）
        # BGE-M3 CPU 推理是同步阻塞调用，必须放线程池，否则会阻塞 FastAPI 事件循环
        # （入库任务在后台执行，但事件循环被占用时所有 API 请求都会超时无响应）
        t0 = time.perf_counter()
        await asyncio.to_thread(encode_texts, ["warmup"])
        model_s = time.perf_counter() - t0

        encode_s = db_s = 0.0
        done = 0
        for start in range(0, len(ids), BATCH_SIZE):
            batch_ids = ids[start : start + BATCH_SIZE]
            rows = (
                await s.execute(
                    select(BookChunk.id, BookChunk.chunk_text).where(BookChunk.id.in_(batch_ids))
                )
            ).all()
            texts = [r.chunk_text for r in rows]

            t1 = time.perf_counter()
            vectors = await asyncio.to_thread(encode_texts, texts)
            encode_s += time.perf_counter() - t1

            t1 = time.perf_counter()
            for (chunk_id, _), vec in zip(rows, vectors):
                await s.execute(
                    BookChunk.__table__.update()
                    .where(BookChunk.id == chunk_id)
                    .values(embedding=vec)
                )
            await s.commit()
            db_s += time.perf_counter() - t1
            done += len(rows)
            print(f"  向量化进度 {done}/{len(ids)}")

    return {"chunks": done, "model_s": model_s, "encode_s": encode_s, "db_s": db_s}


async def run_ingest(gutenberg_ids: list[int], embed: bool = False) -> None:
    """串起完整入库链路，逐环节打印耗时。

    Args:
        gutenberg_ids: 本次爬取成功的书（古登堡 ID），只处理这些书的新增数据。
        embed: 是否同时向量化（CPU 推理约 2.4 块/秒，千块约 8 分钟）。
    """
    if not gutenberg_ids:
        print("[流水线] 本次没有新书，跳过入库")
        return
    t0 = time.perf_counter()
    print(f"[流水线] 开始入库 {len(gutenberg_ids)} 本书：{gutenberg_ids}")

    t1 = time.perf_counter()
    result = await sync_books()
    print(f"[流水线] 1/4 书籍同步：新增 {result.created} 更新 {result.updated}（{time.perf_counter() - t1:.1f}s）")

    t1 = time.perf_counter()
    stats = await sync_chapters_from_local(only_ids=set(gutenberg_ids))
    print(f"[流水线] 2/4 章节切分：{stats['books']} 本书 {stats['chapters']} 章（{time.perf_counter() - t1:.1f}s）")

    t1 = time.perf_counter()
    chunk_stats = await chunk_books(gutenberg_ids)
    print(
        f"[流水线] 3/4 分块：{chunk_stats['chunks']} 块"
        f"（切分 {chunk_stats['split_s']:.2f}s / 写入 {chunk_stats['db_s']:.2f}s，共 {time.perf_counter() - t1:.1f}s）"
    )

    if embed:
        t1 = time.perf_counter()
        # 只补本次入库书籍的缺向量块，避免顺带清全库欠账导致任务时长不可控
        emb = await embed_missing_chunks(gutenberg_ids=gutenberg_ids)
        print(
            f"[流水线] 4/4 向量化：{emb['chunks']} 块"
            f"（模型加载 {emb['model_s']:.1f}s / 编码 {emb['encode_s']:.1f}s / 写库 {emb['db_s']:.1f}s，"
            f"共 {time.perf_counter() - t1:.1f}s）"
        )
    else:
        print("[流水线] 4/4 向量化：跳过（加 --embed 启用，约 2.4 块/秒）")

    # 书库内容有变化：列表缓存立即失效（旧版本 key 靠 TTL 自然过期）
    try:
        from app.services.book_cache import bump_books_cache

        await bump_books_cache(get_redis())
    except Exception as exc:
        print(f"[流水线] 列表缓存失效失败（Redis 不可用？）：{exc}")

    print(f"[流水线] 入库完成，总耗时 {time.perf_counter() - t0:.1f}s")
