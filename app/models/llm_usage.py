from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class LLMUsageLog(Base):
    """LLM 调用流水：记录每次模型调用的场景与 token 用量，供后台成本统计。

    覆盖场景：AI 问答 / 翻译 / 查词 / 查询改写。翻译另存 translation_records
    （字符计费口径），本表统一按 token 统计成本。
    """

    __tablename__ = "llm_usage_log"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    scene: Mapped[str] = mapped_column(String(30), index=True)   # AI 问答 / 翻译 / 查词 / 查询改写
    model: Mapped[str] = mapped_column(String(50), default="")   # 模型名（成本随模型不同）
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
