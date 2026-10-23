"""命令行：解析 data/books 本地书源，切分章节写入 PostgreSQL。

用法：python -m app.scripts.load_chapters
"""
import asyncio

from app.db.database import Base, engine
from app.models import book, book_chapter, reading_progress, user  # noqa: F401
from app.services.chapter_service import sync_chapters_from_local


async def main() -> None:
    # 先确保表结构存在（与应用启动时行为一致）
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    stats = await sync_chapters_from_local()
    print(f"入库完成：{stats['books']} 本书，共 {stats['chapters']} 章，跳过 {stats['skipped']} 本（书籍表无记录）")
    print(
        f"耗时：读取 {stats['read_s']:.2f}s / 切分 {stats['split_s']:.2f}s / "
        f"数据库 {stats['db_s']:.2f}s / 提交 {stats['commit_s']:.2f}s，总 {stats['total_s']:.2f}s"
    )
    title, sec = stats["slowest"]
    if title:
        print(f"最慢一本书：{title}（{sec:.2f}s）")


if __name__ == "__main__":
    asyncio.run(main())
