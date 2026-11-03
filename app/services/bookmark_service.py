"""书签业务逻辑：添加 / 列表 / 删除，附带书籍来源信息。"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.user import User
from app.repositories.book_repository import BookRepository
from app.repositories.bookmark_repository import BookmarkRepository
from app.schemas.study import BookmarkAddRequest, BookmarkOut


class BookmarkService:
    """书签服务"""

    def __init__(self, db: AsyncSession):
        self.bookmark_repo = BookmarkRepository(db)
        self.book_repo = BookRepository(db)

    async def list_bookmarks(self, user: User, book_id: int | None = None) -> list[BookmarkOut]:
        rows = await self.bookmark_repo.list_by_user(user.id, book_id)
        if not rows:
            return []
        books = {b.id: b for b in await self.book_repo.list_by_ids([r.book_id for r in rows])}
        return [
            BookmarkOut(
                id=r.id, book_id=r.book_id, book_title=books[r.book_id].title if r.book_id in books else "",
                chapter_index=r.chapter_index, page_index=r.page_index,
                excerpt=r.excerpt, created_at=r.created_at,
            )
            for r in rows
        ]

    async def add_bookmark(self, user: User, req: BookmarkAddRequest) -> BookmarkOut:
        """添加书签（幂等）：同位置重复添加返回已有条目"""
        book = await self.book_repo.get_by_id(req.book_id)
        if book is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"书籍 {req.book_id} 不存在，无法添加书签")

        existing = await self.bookmark_repo.get_by_position(
            user.id, req.book_id, req.chapter_index, req.page_index
        )
        if existing is not None:
            return BookmarkOut(
                id=existing.id, book_id=existing.book_id, book_title=book.title,
                chapter_index=existing.chapter_index, page_index=existing.page_index,
                excerpt=existing.excerpt, created_at=existing.created_at,
            )
        row = await self.bookmark_repo.add(
            user.id, req.book_id, req.chapter_index, req.page_index, req.excerpt
        )
        return BookmarkOut(
            id=row.id, book_id=row.book_id, book_title=book.title,
            chapter_index=row.chapter_index, page_index=row.page_index,
            excerpt=row.excerpt, created_at=row.created_at,
        )

    async def remove_bookmark(self, user: User, bookmark_id: int) -> None:
        removed = await self.bookmark_repo.remove(user.id, bookmark_id)
        if not removed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "书签不存在或已删除")


def get_bookmark_service(db: AsyncSession = Depends(get_db)) -> BookmarkService:
    return BookmarkService(db)
