from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class TranslationRecord(Base):
    """翻译调用记录：计费/配额的数据基础（暂不限制用量，仅记录）"""

    __tablename__ = "translation_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    provider: Mapped[str] = mapped_column(String(30))          # 翻译通道（deepseek 等）
    source_lang: Mapped[str] = mapped_column(String(30))       # 源语言（auto 为自动检测）
    target_lang: Mapped[str] = mapped_column(String(30))       # 目标语言
    char_count: Mapped[int] = mapped_column(Integer)           # 输入字符数（计费口径）
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
