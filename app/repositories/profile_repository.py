"""个人中心数据访问层：统计聚合、阅读历史、用户设置"""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.book import Book
from app.models.book_interaction import BookInteraction
from app.models.level_test_result import LevelTestResult
from app.models.reading_progress import UserReadingProgress
from app.models.translation_record import TranslationRecord
from app.models.user_settings import UserSetting


class ProfileRepository:
    """个人中心读查询与设置读写（聚合跨表查询，服务于 /me 路由）"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_stats(self, user_id: int) -> dict:
        """一次聚合个人中心各计数项"""
        async def count(model, *conditions):
            result = await self.db.execute(
                select(func.count()).select_from(model).where(*conditions)
            )
            return result.scalar_one()

        read_books = await count(
            UserReadingProgress, UserReadingProgress.user_id == user_id
        )
        liked = await count(
            BookInteraction,
            BookInteraction.user_id == user_id,
            BookInteraction.liked.is_(True),
        )
        favorited = await count(
            BookInteraction,
            BookInteraction.user_id == user_id,
            BookInteraction.favorited.is_(True),
        )
        translations = await count(TranslationRecord, TranslationRecord.user_id == user_id)

        chars_result = await self.db.execute(
            select(func.coalesce(func.sum(TranslationRecord.char_count), 0))
            .where(TranslationRecord.user_id == user_id)
        )
        chars = chars_result.scalar_one()

        latest_level = await self.db.execute(
            select(LevelTestResult.level)
            .where(LevelTestResult.user_id == user_id)
            .order_by(LevelTestResult.created_at.desc())
            .limit(1)
        )
        level = latest_level.scalar_one_or_none()

        return {
            "read_books": read_books,
            "chapters_finished": read_books,  # 进度一人一书一行，章节数与书数同源
            "liked_count": liked,
            "favorite_count": favorited,
            "translation_count": translations,
            "translation_chars": chars,
            "level": level,
        }

    async def list_history(self, user_id: int, limit: int = 20) -> list[tuple]:
        """最近阅读：进度行 join 书籍信息，按更新时间倒序"""
        result = await self.db.execute(
            select(
                UserReadingProgress.book_id,
                Book.title,
                Book.author,
                Book.cover_url,
                UserReadingProgress.chapter_index,
                UserReadingProgress.percent,
                UserReadingProgress.updated_at,
            )
            .join(Book, Book.id == UserReadingProgress.book_id)
            .where(UserReadingProgress.user_id == user_id)
            .order_by(UserReadingProgress.updated_at.desc())
            .limit(limit)
        )
        return list(result.all())

    # ---------------- 用户设置 ----------------

    async def get_settings(self, user_id: int) -> UserSetting | None:
        result = await self.db.execute(
            select(UserSetting).where(UserSetting.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def upsert_settings(self, user_id: int, target_lang: str) -> UserSetting:
        """存在则更新目标语言，否则新建（一人一行）"""
        setting = await self.get_settings(user_id)
        if setting is None:
            setting = UserSetting(user_id=user_id, target_lang=target_lang)
            self.db.add(setting)
        else:
            setting.target_lang = target_lang
        await self.db.commit()
        await self.db.refresh(setting)
        return setting
