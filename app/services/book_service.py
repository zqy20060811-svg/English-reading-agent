import json
from pathlib import Path

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.books_catalog import BOOK_CATALOG
from app.crawler.scraper import DEFAULT_OUTPUT_DIR
from app.db.database import get_db
from app.models.book import Book
from app.repositories.book_repository import BookRepository
from app.repositories.chapter_repository import ChapterRepository
from app.schemas.book import BookSyncResult


class BookService:
    """书籍查询与数据同步业务逻辑"""

    def __init__(self, db: AsyncSession):
        self.repo = BookRepository(db)
        self.chapter_repo = ChapterRepository(db)

    async def list_chapters(self, book_id: int) -> tuple[Book, list]:
        """返回书籍与章节目录；书籍不存在或未入库章节时返回 404。"""
        book = await self.repo.get_by_id(book_id)
        if book is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"书籍 {book_id} 不存在")
        chapters = await self.chapter_repo.list_by_book(book_id)
        if not chapters:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"书籍「{book.title}」暂无章节数据，请先运行 python -m app.scripts.load_chapters",
            )
        return book, chapters

    async def get_chapter(self, book_id: int, chapter_index: int):
        """获取指定章节详情（含正文）；书籍或章节不存在时返回 404。"""
        book = await self.repo.get_by_id(book_id)
        if book is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"书籍 {book_id} 不存在")
        chapter = await self.chapter_repo.get_by_book_and_index(book_id, chapter_index)
        if chapter is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"书籍「{book.title}」不存在第 {chapter_index} 章",
            )
        return book, chapter

    async def list_all(self, limit: int = 100) -> list[Book]:
        """全部书籍列表（按入库顺序），供前端书架使用"""
        return await self.repo.list_all(limit)

    async def search_by_title(self, title: str) -> list[Book]:
        """按书名查询书籍简介，未命中时返回 404。"""
        books = await self.repo.search_by_title(title.strip())
        if not books:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"未找到书名包含“{title}”的书籍")
        return books

    async def sync_from_crawler(
        self, books_dir: Path = DEFAULT_OUTPUT_DIR
    ) -> BookSyncResult:
        """将本地爬取结果（data/books/*/info.json）同步入库。

        数据库只存书籍信息与简介，不存正文。
        简介优先取 info.json；早期爬取结果缺简介时，回退到书单目录补齐。
        """
        if not books_dir.exists():
            raise HTTPException(
                status.HTTP_404_NOT_FOUND,
                f"爬取结果目录不存在：{books_dir}，请先运行 python -m app.crawler",
            )

        total = created = updated = 0
        for info_path in sorted(books_dir.glob("*/info.json")):
            info = json.loads(info_path.read_text(encoding="utf-8"))
            gutenberg_id = info.get("gutenberg_id")
            if not gutenberg_id:
                continue
            total += 1

            synopsis = info.get("synopsis") or self._catalog_synopsis(gutenberg_id) or ""
            fields = {
                "title": info["title"],
                "author": info["author"],
                "year": info["year"],
                "genre": info.get("genre", ""),
                "synopsis": synopsis,
                "language": info.get("language", "en"),
                "source_url": info.get("source_url", ""),
                "word_count": info.get("word_count", 0),
            }

            existing = await self.repo.get_by_gutenberg_id(gutenberg_id)
            if existing:
                await self.repo.update(existing, **fields)
                updated += 1
            else:
                await self.repo.create(Book(gutenberg_id=gutenberg_id, **fields))
                created += 1

        return BookSyncResult(total_found=total, created=created, updated=updated)

    @staticmethod
    def _catalog_synopsis(gutenberg_id: int) -> str | None:
        """从书单目录中按 Gutenberg 编号查找简介。"""
        for book in BOOK_CATALOG:
            if book.gutenberg_id == gutenberg_id:
                return book.synopsis
        return None


def get_book_service(db: AsyncSession = Depends(get_db)) -> BookService:
    return BookService(db)
