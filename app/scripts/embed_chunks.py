"""命令行：为 book_chunks 中缺 embedding 的块生成向量（BAAI/bge-small-en-v1.5 本地推理）。

用法：python -m app.scripts.embed_chunks [--limit N]
"""
import asyncio

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.models.book import Book  # noqa: F401 确保外键表注册
from app.models.book_chunk import BookChunk

MODEL_NAME = "BAAI/bge-small-en-v1.5"
BATCH_SIZE = 64


def get_model():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(MODEL_NAME)


async def embed_chunks(limit: int | None = None) -> int:
    """分批为缺失 embedding 的块生成向量并更新入库，返回处理的块数。"""
    async with AsyncSessionLocal() as s:
        id_q = select(BookChunk.id).where(BookChunk.embedding.is_(None))
        if limit:
            id_q = id_q.limit(limit)
        ids = (await s.execute(id_q)).scalars().all()
        if not ids:
            return 0

        model = get_model()
        done = 0
        for start in range(0, len(ids), BATCH_SIZE):
            batch_ids = ids[start : start + BATCH_SIZE]
            rows = (
                await s.execute(
                    select(BookChunk.id, BookChunk.chunk_text).where(BookChunk.id.in_(batch_ids))
                )
            ).all()
            texts = [r.chunk_text for r in rows]
            vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
            for (chunk_id, _), vec in zip(rows, vectors):
                await s.execute(
                    BookChunk.__table__.update()
                    .where(BookChunk.id == chunk_id)
                    .values(embedding=vec.tolist())
                )
            await s.commit()
            done += len(rows)
            print(f"  进度 {done}/{len(ids)}")
        return done


async def main() -> None:
    import sys

    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])
    n = await embed_chunks(limit)
    print(f"embedding 生成完成：{n} 块（模型 {MODEL_NAME}，384 维，已归一化）")


if __name__ == "__main__":
    asyncio.run(main())
