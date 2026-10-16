"""命令行：对全部章节递归字符分块，写入 book_chunks 表（幂等全量重建）。

用法：
    python -m app.scripts.load_chunks            # 分块并入库
    python -m app.scripts.load_chunks --dry-run  # 仅预览统计，不写库
"""
import asyncio
from collections import Counter

from app.db.database import AsyncSessionLocal
from app.services.chunk_service import CHUNK_OVERLAP, CHUNK_SIZE, ChunkService, recursive_split


async def main(dry_run: bool) -> None:
    if dry_run:
        from sqlalchemy import select
        from app.models.book_chapter import BookChapter

        async with AsyncSessionLocal() as s:
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

    async with AsyncSessionLocal() as db:
        stats = await ChunkService(db).chunk_all_books()
    print(f"分块入库完成：{stats['chapters']} 章，共 {stats['chunks']} 块")


if __name__ == "__main__":
    import sys

    asyncio.run(main("--dry-run" in sys.argv))
