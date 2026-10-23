"""新书入库流水线：书籍同步 → 章节切分 → 分块 → 向量化。

供爬虫（--ingest / --embed）与独立脚本复用，各环节带耗时统计。
原始正文始终落盘 data/books/（作为重新切分/重建向量的数据源），本流水线
只负责把磁盘内容推进数据库。
"""
import time

from sqlalchemy import delete, select

from app.chunking import recursive_split
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
    """按古登堡 ID 重建分块（None 表示全部书），返回统计与各环节耗时。"""
    t0 = time.perf_counter()
    async with AsyncSessionLocal() as s:
        stmt = select(BookChapter.id, BookChapter.book_id, BookChapter.content)
        if gutenberg_ids:
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


async def embed_missing_chunks(limit: int | None = None) -> dict:
    """为 book_chunks 中缺 embedding 的块生成向量（BGE-M3 本地推理）。

    返回处理的块数与耗时拆分：model_s 模型加载、encode_s 编码、db_s 写库。
    app.embedding 延迟导入，避免不向量化时加载 sentence-transformers。
    """
    from app.embedding import encode_texts

    BATCH_SIZE = 32
    async with AsyncSessionLocal() as s:
        id_q = select(BookChunk.id).where(BookChunk.embedding.is_(None))
        if limit:
            id_q = id_q.limit(limit)
        ids = (await s.execute(id_q)).scalars().all()
        if not ids:
            return {"chunks": 0, "model_s": 0.0, "encode_s": 0.0, "db_s": 0.0}

        # 模型加载单独计时（首次调用 encode_texts 时触发 lru_cache 单例加载）
        t0 = time.perf_counter()
        encode_texts(["warmup"])
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
            vectors = encode_texts(texts)
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
        emb = await embed_missing_chunks()
        print(
            f"[流水线] 4/4 向量化：{emb['chunks']} 块"
            f"（模型加载 {emb['model_s']:.1f}s / 编码 {emb['encode_s']:.1f}s / 写库 {emb['db_s']:.1f}s，"
            f"共 {time.perf_counter() - t1:.1f}s）"
        )
    else:
        print("[流水线] 4/4 向量化：跳过（加 --embed 启用，约 2.4 块/秒）")

    print(f"[流水线] 入库完成，总耗时 {time.perf_counter() - t0:.1f}s")
