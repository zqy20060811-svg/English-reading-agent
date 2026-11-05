"""生词本数据访问层"""

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_vocabulary import UserVocabulary
from app.models.vocabulary_group import VocabularyGroup


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
        self, user_id: int, book_id: int | None, word: str,
        chapter_index: int, context_sentence: str | None,
    ) -> UserVocabulary:
        """收录生词（词已归一化为小写）；book_id 为空表示来自个人书籍。

        原子插入：并发重复收录时唯一约束兜底，冲突则返回已有条目（幂等）。
        """
        stmt = (
            pg_insert(UserVocabulary)
            .values(
                user_id=user_id,
                book_id=book_id,
                word=word,
                chapter_index=chapter_index,
                context_sentence=context_sentence,
            )
            .on_conflict_do_nothing(index_elements=["user_id", "word"])
            .returning(UserVocabulary)
        )
        result = await self.db.execute(stmt)
        row = result.scalar_one_or_none()
        await self.db.commit()
        if row is not None:
            return row
        return await self.get_by_word(user_id, word)

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

    # ---------- 自定义分组 ----------

    async def list_groups(self, user_id: int) -> list[tuple[VocabularyGroup, int]]:
        """用户全部分组及各组词数，按 position 升序"""
        counts = {
            gid: cnt
            for gid, cnt in (
                await self.db.execute(
                    select(UserVocabulary.group_id, func.count())
                    .where(UserVocabulary.user_id == user_id)
                    .group_by(UserVocabulary.group_id)
                )
            ).all()
        }
        rows = await self.db.execute(
            select(VocabularyGroup)
            .where(VocabularyGroup.user_id == user_id)
            .order_by(VocabularyGroup.position, VocabularyGroup.id)
        )
        return [(g, counts.get(g.id, 0)) for g in rows.scalars().all()]

    async def get_group(self, user_id: int, group_id: int) -> VocabularyGroup | None:
        result = await self.db.execute(
            select(VocabularyGroup).where(
                VocabularyGroup.user_id == user_id,
                VocabularyGroup.id == group_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_group_by_name(self, user_id: int, name: str) -> VocabularyGroup | None:
        result = await self.db.execute(
            select(VocabularyGroup).where(
                VocabularyGroup.user_id == user_id,
                VocabularyGroup.name == name,
            )
        )
        return result.scalar_one_or_none()

    async def count_groups(self, user_id: int) -> int:
        result = await self.db.execute(
            select(func.count()).select_from(VocabularyGroup)
            .where(VocabularyGroup.user_id == user_id)
        )
        return result.scalar_one()

    async def add_group(self, user_id: int, name: str, position: int) -> VocabularyGroup:
        group = VocabularyGroup(user_id=user_id, name=name, position=position)
        self.db.add(group)
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def update_group(
        self, group: VocabularyGroup, name: str | None, position: int | None
    ) -> VocabularyGroup:
        if name is not None:
            group.name = name
        if position is not None:
            group.position = position
        await self.db.commit()
        await self.db.refresh(group)
        return group

    async def delete_group(self, group: VocabularyGroup) -> None:
        """删除分组；组内生词经外键 ondelete=SET NULL 自动回落未分组"""
        await self.db.delete(group)
        await self.db.commit()

    async def move_word(self, user_id: int, word_id: int, group_id: int | None) -> int:
        """移动生词到分组（None=未分组），返回更新行数（0=词不存在）"""
        result = await self.db.execute(
            select(UserVocabulary).where(
                UserVocabulary.user_id == user_id,
                UserVocabulary.id == word_id,
            )
        )
        word = result.scalar_one_or_none()
        if word is None:
            return 0
        word.group_id = group_id
        await self.db.commit()
        return 1
