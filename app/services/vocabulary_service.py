"""生词本业务逻辑：收录 / 列表 / 删除，附带书籍来源信息。"""

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.user import User
from app.repositories.book_repository import BookRepository
from app.repositories.vocabulary_repository import VocabularyRepository
from app.schemas.study import VocabularyAddRequest, VocabularyOut


def normalize_word(word: str) -> str:
    """生词归一化：去首尾空白并转小写，保证同一单词跨大小写去重"""
    return word.strip().lower()


class VocabularyService:
    """生词本服务"""

    def __init__(self, db: AsyncSession):
        self.vocab_repo = VocabularyRepository(db)
        self.book_repo = BookRepository(db)

    async def list_words(self, user: User) -> list[VocabularyOut]:
        rows = await self.vocab_repo.list_by_user(user.id)
        if not rows:
            return []
        books = {b.id: b for b in await self.book_repo.list_by_ids([r.book_id for r in rows])}
        return [
            VocabularyOut(
                id=r.id, book_id=r.book_id, book_title=books[r.book_id].title if r.book_id in books else "",
                word=r.word, context_sentence=r.context_sentence,
                chapter_index=r.chapter_index, created_at=r.created_at,
            )
            for r in rows
        ]

    async def add_word(self, user: User, req: VocabularyAddRequest) -> VocabularyOut:
        """收录生词（幂等）：书籍需存在，重复收录直接返回已有条目"""
        book = await self.book_repo.get_by_id(req.book_id)
        if book is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"书籍 {req.book_id} 不存在，无法收录生词")

        word = normalize_word(req.word)
        if not word:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "生词不能为空")

        existing = await self.vocab_repo.get_by_word(user.id, word)
        if existing is not None:
            return VocabularyOut(
                id=existing.id, book_id=existing.book_id, book_title=book.title if existing.book_id == book.id else "",
                word=existing.word, context_sentence=existing.context_sentence,
                chapter_index=existing.chapter_index, created_at=existing.created_at,
            )
        row = await self.vocab_repo.add(
            user.id, book.id, word, req.chapter_index, req.context_sentence
        )
        return VocabularyOut(
            id=row.id, book_id=row.book_id, book_title=book.title,
            word=row.word, context_sentence=row.context_sentence,
            chapter_index=row.chapter_index, created_at=row.created_at,
        )

    async def remove_word(self, user: User, word_id: int) -> None:
        removed = await self.vocab_repo.remove(user.id, word_id)
        if not removed:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "生词不存在或已删除")


def get_vocabulary_service(db: AsyncSession = Depends(get_db)) -> VocabularyService:
    return VocabularyService(db)
