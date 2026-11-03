from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class IngestTask(Base):
    """书籍入库任务：管理员触发的 爬取→入库→切章→分块→向量化 异步任务。

    状态机：pending（待执行）→ running（执行中）→ success / failed
    失败任务可由管理员重试（重置为 pending 重新执行，attempts 累加）。
    """

    __tablename__ = "ingest_tasks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    gutenberg_id: Mapped[int] = mapped_column(Integer, index=True)  # 古登堡书号
    embed: Mapped[bool] = mapped_column(Boolean, default=False)     # 是否同时向量化（CPU 慢）
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)       # 已执行次数（含重试）
    error: Mapped[str | None] = mapped_column(Text, nullable=True)  # 失败原因
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
