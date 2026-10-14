"""阅读进度业务逻辑：查询/保存用户在某本书的阅读位置。"""

from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.user import User
from app.repositories.book_repository import BookRepository
from app.repositories.chapter_repository import ChapterRepository
from app.repositories.reading_progress_repository import ReadingProgressRepository
from app.schemas.reading import ReadingProgressOut, ReadingProgressUpdate


class ReadingService:
    """阅读进度服务"""

    def __init__(self, db: AsyncSession):
        self.progress_repo = ReadingProgressRepository(db)
        self.chapter_repo = ChapterRepository(db)
        self.book_repo = BookRepository(db)

    async def get_progress(self, user: User, book_id: int) -> ReadingProgressOut:
        """获取用户上次阅读位置。

        - 书籍不存在：404
        - 书籍存在、用户尚无阅读记录：返回初始进度（第 1 章、偏移 0、0%）
        - 已读过：返回数据库保存的进度
        """
        book = await self.book_repo.get_by_id(book_id)
        if book is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"书籍 {book_id} 不存在")
        row = await self.progress_repo.get(user.id, book_id)
        if row is None:
            return ReadingProgressOut(
                book_id=book_id,
                chapter_index=1,
                char_offset=0,
                percent=0.0,
                updated_at=datetime.now(timezone.utc),
            )
        return ReadingProgressOut.model_validate(row)

    async def save_progress(self, user: User, book_id: int, data: ReadingProgressUpdate):
        """保存阅读进度。

        校验：书籍存在、章节存在、char_offset 不超过章节正文长度；否则 400。
        """
        book = await self.book_repo.get_by_id(book_id)
        if book is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"书籍 {book_id} 不存在，无法保存进度")
        chapter = await self.chapter_repo.get_by_book_and_index(book_id, data.chapter_index)
        if chapter is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"书籍「{book.title}」不存在第 {data.chapter_index} 章，无法保存进度",
            )
        if data.char_offset > len(chapter.content):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"字符偏移 {data.char_offset} 超出章节「{chapter.title}」正文长度 {len(chapter.content)}",
            )
        return await self.progress_repo.upsert(
            user.id, book_id, data.chapter_index, data.char_offset, data.percent
        )


def get_reading_service(db: AsyncSession = Depends(get_db)) -> ReadingService:
    return ReadingService(db)
