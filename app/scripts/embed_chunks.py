"""命令行：为 book_chunks 中缺 embedding 的块生成向量（BAAI/bge-m3 本地推理，1024 维中英文）。

用法：python -m app.scripts.embed_chunks [--limit N] [--shard I --shards M]
分片参数用于多进程并行加速（id % shards == shard 的块由本进程处理）。
"""
import asyncio

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.embedding import MODEL_NAME, encode_texts
from app.models.book import Book  # noqa: F401 确保外键表注册
from app.models.book_chunk import BookChunk

BATCH_SIZE = 32


async def embed_chunks(limit: int | None = None, shard: int | None = None, shards: int | None = None) -> int:
    """分批为缺失 embedding 的块生成向量并更新入库，返回处理的块数。"""
    async with AsyncSessionLocal() as s:
        id_q = select(BookChunk.id).where(BookChunk.embedding.is_(None))
        if shard is not None and shards:
            id_q = id_q.where(BookChunk.id % shards == shard)
        if limit:
            id_q = id_q.limit(limit)
        ids = (await s.execute(id_q)).scalars().all()
        if not ids:
            return 0

        done = 0
        for start in range(0, len(ids), BATCH_SIZE):
            batch_ids = ids[start : start + BATCH_SIZE]
            rows = (
                await s.execute(
                    select(BookChunk.id, BookChunk.chunk_text).where(BookChunk.id.in_(batch_ids))
                )
            ).all()
            texts = [r.chunk_text for r in rows]
            vectors = encode_texts(texts)  # 共用 app.embedding 单例模型
            for (chunk_id, _), vec in zip(rows, vectors):
                await s.execute(
                    BookChunk.__table__.update()
                    .where(BookChunk.id == chunk_id)
                    .values(embedding=vec)
                )
            await s.commit()
            done += len(rows)
            print(f"  进度 {done}/{len(ids)}")
        return done


async def main() -> None:
    import sys

    limit = shard = shards = None
    argv = sys.argv
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    if "--shard" in argv and "--shards" in argv:
        shard = int(argv[argv.index("--shard") + 1])
        shards = int(argv[argv.index("--shards") + 1])
    n = await embed_chunks(limit, shard, shards)
    tag = f"，分片 {shard}/{shards}" if shard is not None else ""
    print(f"embedding 生成完成：{n} 块（模型 {MODEL_NAME}，1024 维，已归一化{tag}）")


if __name__ == "__main__":
    asyncio.run(main())
