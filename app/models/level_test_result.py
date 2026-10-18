from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class LevelTestResult(Base):
    """英语水平测试结果：每个用户可多次测试，保留历史记录"""

    __tablename__ = "user_level_tests"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    total_score: Mapped[int] = mapped_column(Integer)          # 加权总分
    max_score: Mapped[int] = mapped_column(Integer)            # 满分（随题库规模而定）
    level: Mapped[str] = mapped_column(String(8))              # 评估等级（A1~C1）
    vocabulary_acc: Mapped[float] = mapped_column(Float)       # 词汇正确率 0~1
    grammar_acc: Mapped[float] = mapped_column(Float)          # 语法正确率 0~1
    reading_acc: Mapped[float] = mapped_column(Float)          # 阅读正确率 0~1
    recommended_level: Mapped[str] = mapped_column(String(8))  # 推荐阅读难度等级
    details: Mapped[dict] = mapped_column(JSON)                # 逐维度/逐等级明细 JSON
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
