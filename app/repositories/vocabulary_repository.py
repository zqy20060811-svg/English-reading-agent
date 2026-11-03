"""生词本数据访问层"""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_vocabulary import UserVocabulary


class VocabularyRepository:
    """生词本表数据访问层"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_user(self, user_id: int) -> list[UserVocabulary]:
        """用户全部生词，按收藏时间倒序"""
        result = await self.db.execute(
            select(UserVocabulary)
            .where(UserVocabulary.user_id == user_id)
            .order_by(UserVocabulary.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_by_word(self, user_id: int, word: str) -> UserVocabulary | None:
        result = await self.db.execute(
            select(UserVocabulary).where(
                UserVocabulary.user_id == user_id,
                UserVocabulary.word == word,
            )
        )
        return result.scalar_one_or_none()

    async def add(
        self, user_id: int, book_id: int, word: str,
        chapter_index: int, context_sentence: str | None,
    ) -> UserVocabulary:
        """收录生词（词已归一化为小写）"""
        row = UserVocabulary(
            user_id=user_id,
            book_id=book_id,
            word=word,
            chapter_index=chapter_index,
            context_sentence=context_sentence,
        )
        self.db.add(row)
        await self.db.commit()
        await self.db.refresh(row)
        return row

    async def remove(self, user_id: int, word_id: int) -> int:
        """删除生词，返回删除行数（0 表示不存在）"""
        result = await self.db.execute(
            delete(UserVocabulary).where(
                UserVocabulary.user_id == user_id,
                UserVocabulary.id == word_id,
            )
        )
        await self.db.commit()
        return result.rowcount or 0
