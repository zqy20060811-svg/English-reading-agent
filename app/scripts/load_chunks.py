"""命令行：对全部章节递归字符分块，写入 book_chunks 表（幂等全量重建）。

复用 app.pipeline.chunk_books 核心逻辑。

用法：
    python -m app.scripts.load_chunks                    # 分块并入库（全部书）
    python -m app.scripts.load_chunks --book 15          # 只处理某本古登堡 ID 的书
    python -m app.scripts.load_chunks --book 101 --book 102   # 多本书（新书入库推荐）
    python -m app.scripts.load_chunks --dry-run          # 仅预览统计，不写库
"""
import argparse
import asyncio
from collections import Counter

from sqlalchemy import select

from app.chunking import CHUNK_OVERLAP, CHUNK_SIZE, recursive_split
from app.db.database import AsyncSessionLocal
from app.models.book_chapter import BookChapter
from app.pipeline import chunk_books


async def dry_run() -> None:
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


async def main(gutenberg_ids: list[int] | None = None) -> None:
    stats = await chunk_books(gutenberg_ids)
    print(f"分块入库完成：{stats['chapters']} 章，共 {stats['chunks']} 块")
    print(f"耗时：切分 {stats['split_s']:.2f}s / 组装写入 {stats['db_s']:.2f}s / 提交 {stats['commit_s']:.2f}s")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="仅预览统计，不写库")
    parser.add_argument(
        "--book", type=int, action="append", help="只处理指定古登堡 ID 的书（可多次传入）"
    )
    args = parser.parse_args()
    if args.dry_run:
        asyncio.run(dry_run())
    else:
        asyncio.run(main(args.book))
