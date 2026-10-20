from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.translation_record import TranslationRecord


class TranslationRepository:
    """翻译调用记录数据访问层（为后续配额/计费预留查询）"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def save(self, record: TranslationRecord) -> TranslationRecord:
        self.db.add(record)
        await self.db.commit()
        await self.db.refresh(record)
        return record

    async def count_recent(self, user_id: int) -> int:
        """用户累计调用次数（预留：后续配额限制/计费时扩展时间窗口与字符数统计）"""
        result = await self.db.execute(
            select(TranslationRecord).where(TranslationRecord.user_id == user_id)
        )
        return len(result.scalars().all())
