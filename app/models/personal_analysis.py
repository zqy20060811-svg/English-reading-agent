"""个人书籍 AI 全书预分析：任务表 + 章节结果表 + 全书报告表。

与公共书库入库任务（ingest_tasks）风格一致但独立设计：
- 全部数据绑定 user_id + personal_book_id（用户隔离的硬边界）
- 任务状态机：pending → running → completed / failed / cancelled
- 章节结果逐章落库（每完成一章立即提交），失败章节可续跑
- 部分唯一索引保证同一本书同时只有一个进行中任务（pending/running）
- 删除个人书籍时随外键 CASCADE 一并清理
"""

from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


def _now():
    return datetime.now(timezone.utc)


class PersonalAnalysisTask(Base):
    """个人书籍分析任务：全书按章节分析的整体进度与状态。"""

    __tablename__ = "personal_analysis_tasks"

    # 进行中状态集合（与部分唯一索引 uq_personal_analysis_active_book 保持一致）
    ACTIVE_STATUSES = ("pending", "running")

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    personal_book_id: Mapped[int] = mapped_column(
        ForeignKey("personal_books.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    total_chapters: Mapped[int] = mapped_column(Integer, default=0)
    completed_chapters: Mapped[int] = mapped_column(Integer, default=0)
    failed_chapters: Mapped[int] = mapped_column(Integer, default=0)
    current_chapter_index: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


# 部分唯一索引：同一本书只允许一个 pending/running 任务（照抄 ingest_tasks 的防重做法）
Index(
    "uq_personal_analysis_active_book",
    PersonalAnalysisTask.personal_book_id,
    unique=True,
    postgresql_where=PersonalAnalysisTask.status.in_(("pending", "running")),
)


class PersonalChapterAnalysis(Base):
    """章节分析结果：每章分析完成后立即单独保存（失败不影响已完成章节）。"""

    __tablename__ = "personal_chapter_analyses"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "personal_book_id", "chapter_index",
            name="uq_personal_chapter_analysis",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    personal_book_id: Mapped[int] = mapped_column(
        ForeignKey("personal_books.id", ondelete="CASCADE"), index=True
    )
    chapter_index: Mapped[int] = mapped_column(Integer)  # 从 1 开始，对应章节表

    # ---- 本地统计（不调 LLM）----
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    unique_word_count: Mapped[int] = mapped_column(Integer, default=0)
    average_sentence_length: Mapped[float] = mapped_column(Float, default=0.0)
    long_sentence_ratio: Mapped[float] = mapped_column(Float, default=0.0)
    # {A1:n, A2:n, B1:n, B2:n, C1:n, C2:n, unknown:n}（无可靠等级数据的词记 unknown）
    vocabulary_level_distribution: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 词频分布 top / 高频基础词 / 中高级词汇 / 疑似专业词等本地统计明细
    vocabulary_statistics: Mapped[dict] = mapped_column(JSONB, default=dict)
    # 本地规则初筛的语法特征计数 + LLM 分析的代表性难点（含来源标注）
    grammar_features: Mapped[dict] = mapped_column(JSONB, default=dict)

    # ---- LLM 分析结论 ----
    difficulty_level: Mapped[str] = mapped_column(String(8))       # A1~C2
    difficulty_score: Mapped[float] = mapped_column(Float)          # 0~100
    chapter_summary: Mapped[str] = mapped_column(Text, default="")
    reading_suggestion: Mapped[str] = mapped_column(Text, default="")

    analysis_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )


class PersonalBookAnalysis(Base):
    """全书分析报告：所有章节分析完成后汇总生成（一本书一份）。"""

    __tablename__ = "personal_book_analyses"
    __table_args__ = (
        UniqueConstraint("user_id", "personal_book_id", name="uq_personal_book_analysis"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    personal_book_id: Mapped[int] = mapped_column(
        ForeignKey("personal_books.id", ondelete="CASCADE"), index=True
    )
    overall_level: Mapped[str] = mapped_column(String(8))          # A1~C2
    difficulty_score: Mapped[float] = mapped_column(Float)          # 章节加权平均
    total_word_count: Mapped[int] = mapped_column(Integer, default=0)
    # {A1:n, ...}：各难度等级的章节数量
    chapter_difficulty_distribution: Mapped[dict] = mapped_column(JSONB, default=dict)
    vocabulary_level_distribution: Mapped[dict] = mapped_column(JSONB, default=dict)
    main_grammar_features: Mapped[dict] = mapped_column(JSONB, default=dict)
    reading_recommendations: Mapped[list] = mapped_column(JSONB, default=list)
    analysis_version: Mapped[int] = mapped_column(Integer, default=1)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_now, onupdate=_now
    )
