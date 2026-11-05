from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class VocabularyGroup(Base):
    """生词本自定义分组：用户自建的生词分类（如"单元1""重点词"）"""

    __tablename__ = "vocabulary_groups"
    __table_args__ = (
        UniqueConstraint("user_id", "name", name="uq_vocabulary_group_user_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    name: Mapped[str] = mapped_column(String(32))  # 分组名（每用户内唯一）
    position: Mapped[int] = mapped_column(Integer, default=0)  # 展示顺序（小的在前）
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
