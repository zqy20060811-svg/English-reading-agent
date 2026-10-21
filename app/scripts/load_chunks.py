"""命令行：对全部章节递归字符分块，写入 book_chunks 表（幂等全量重建）。

用法：
    python -m app.scripts.load_chunks                    # 分块并入库（全部书）
    python -m app.scripts.load_chunks --book 15          # 只处理某本古登堡 ID 的书
    python -m app.scripts.load_chunks --dry-run          # 仅预览统计，不写库
"""
import asyncio
from collections import Counter

from sqlalchemy import delete, select

from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE, recursive_split
from app.db.database import AsyncSessionLocal
from app.models.book import Book  # noqa: F401 确保外键表注册
from app.models.book_chapter import BookChapter
from app.models.book_chunk import BookChunk


async def main(dry_run: bool, gutenberg_id: int | None = None) -> None:
    async with AsyncSessionLocal() as s:
        if dry_run:
            rows = (await s.execute(select(BookChapter.content))).all()
            sizes = Counter()
            for (content,) in rows:
                for c in recursive_split(content):
                    sizes[len(c) // 200] += 1
            total = sum(sizes.values())
            print(f"预览：{len(rows)} 章，共 {total} 块（chunk_size={CHUNK_SIZE}, overlap={CHUNK_OVERLAP}）")
            for bucket in sorted(sizes):
                print(f"  {bucket * 200:>5}-{bucket * 200 + 199:<5} 字符: {sizes[bucket]} 块")
            return

        # 可选：只处理指定古登堡 ID 的书（用于单书重建，不动其他书的向量块）
        stmt = select(BookChapter.id, BookChapter.book_id, BookChapter.content)
        if gutenberg_id is not None:
            stmt = (
                stmt.where(BookChapter.book_id == Book.id)
                .where(Book.gutenberg_id == gutenberg_id)
            )
        rows = (await s.execute(stmt)).all()
        total = 0
        for chapter_id, book_id, content in rows:
            await s.execute(delete(BookChunk).where(BookChunk.chapter_id == chapter_id))
            for idx, chunk_text in enumerate(recursive_split(content)):
                s.add(
                    BookChunk(
                        book_id=book_id,
                        chapter_id=chapter_id,
                        chunk_index=idx,
                        chunk_text=chunk_text,
                    )
                )
                total += 1
        await s.commit()
    print(f"分块入库完成：{len(rows)} 章，共 {total} 块")


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="仅预览统计，不写库")
    parser.add_argument("--book", type=int, help="只处理指定古登堡 ID 的书")
    args = parser.parse_args()
    asyncio.run(main(args.dry_run, args.book))
