"""阅读进度业务逻辑：查询/保存用户在某本书的阅读位置。"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.user import User
from app.repositories.chapter_repository import ChapterRepository
from app.repositories.reading_progress_repository import ReadingProgressRepository
from app.schemas.reading import ReadingProgressUpdate


class ReadingService:
    """阅读进度服务"""

    def __init__(self, db: AsyncSession):
        self.progress_repo = ReadingProgressRepository(db)
        self.chapter_repo = ChapterRepository(db)

    async def get_progress(self, user: User, book_id: int):
        """获取用户上次阅读位置，无记录时返回 404。"""
        row = await self.progress_repo.get(user.id, book_id)
        if row is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "暂无该书阅读记录")
        return row

    async def save_progress(self, user: User, book_id: int, data: ReadingProgressUpdate):
        """保存阅读进度；章节不存在时返回 400。"""
        if not await self.chapter_repo.exists(book_id, data.chapter_index):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"书籍 {book_id} 不存在第 {data.chapter_index} 章，无法保存进度",
            )
        return await self.progress_repo.upsert(
            user.id, book_id, data.chapter_index, data.char_offset, data.percent
        )


def get_reading_service(db: AsyncSession = Depends(get_db)) -> ReadingService:
    return ReadingService(db)
