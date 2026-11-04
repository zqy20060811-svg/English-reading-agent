"""个人书籍AI全书分析：任务/章节结果/全书报告三张表 + LLM用量耗时列

- personal_analysis_tasks：分析任务状态机（pending→running→completed/failed/cancelled），
  部分唯一索引保证同一本书只有一个进行中任务
- personal_chapter_analyses：章节分析结果逐章落库（同人同书同章唯一，随书级联删除）
- personal_book_analyses：全书难度报告（同人同书唯一，随书级联删除）
- llm_usage_log 增加 duration_ms 可空列：后台分析按调用记录耗时

Revision ID: a9d2f4c7b618
Revises: e5b7c1a93d42
Create Date: 2026-11-04
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "a9d2f4c7b618"
down_revision = "e5b7c1a93d42"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_analysis_tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("personal_book_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("total_chapters", sa.Integer(), nullable=False),
        sa.Column("completed_chapters", sa.Integer(), nullable=False),
        sa.Column("failed_chapters", sa.Integer(), nullable=False),
        sa.Column("current_chapter_index", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["personal_book_id"], ["personal_books.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_analysis_tasks_user_id", "personal_analysis_tasks", ["user_id"])
    op.create_index(
        "ix_personal_analysis_tasks_personal_book_id",
        "personal_analysis_tasks",
        ["personal_book_id"],
    )
    op.create_index("ix_personal_analysis_tasks_status", "personal_analysis_tasks", ["status"])
    op.create_index("ix_personal_analysis_tasks_created_at", "personal_analysis_tasks", ["created_at"])
    # 部分唯一索引：同一本书同时只允许一个 pending/running 任务
    op.create_index(
        "uq_personal_analysis_active_book",
        "personal_analysis_tasks",
        ["personal_book_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )

    op.create_table(
        "personal_chapter_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("personal_book_id", sa.Integer(), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("unique_word_count", sa.Integer(), nullable=False),
        sa.Column("average_sentence_length", sa.Float(), nullable=False),
        sa.Column("long_sentence_ratio", sa.Float(), nullable=False),
        sa.Column(
            "vocabulary_level_distribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("vocabulary_statistics", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("grammar_features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("difficulty_level", sa.String(length=8), nullable=False),
        sa.Column("difficulty_score", sa.Float(), nullable=False),
        sa.Column("chapter_summary", sa.Text(), nullable=False),
        sa.Column("reading_suggestion", sa.Text(), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["personal_book_id"], ["personal_books.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "personal_book_id", "chapter_index", name="uq_personal_chapter_analysis"
        ),
    )
    op.create_index(
        "ix_personal_chapter_analyses_user_id", "personal_chapter_analyses", ["user_id"]
    )
    op.create_index(
        "ix_personal_chapter_analyses_personal_book_id",
        "personal_chapter_analyses",
        ["personal_book_id"],
    )

    op.create_table(
        "personal_book_analyses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("personal_book_id", sa.Integer(), nullable=False),
        sa.Column("overall_level", sa.String(length=8), nullable=False),
        sa.Column("difficulty_score", sa.Float(), nullable=False),
        sa.Column("total_word_count", sa.Integer(), nullable=False),
        sa.Column(
            "chapter_difficulty_distribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "vocabulary_level_distribution",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("main_grammar_features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reading_recommendations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("analysis_version", sa.Integer(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["personal_book_id"], ["personal_books.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "personal_book_id", name="uq_personal_book_analysis"),
    )
    op.create_index("ix_personal_book_analyses_user_id", "personal_book_analyses", ["user_id"])
    op.create_index(
        "ix_personal_book_analyses_personal_book_id",
        "personal_book_analyses",
        ["personal_book_id"],
    )

    # LLM 用量流水补充耗时列（后台分析按调用记录）
    op.add_column("llm_usage_log", sa.Column("duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("llm_usage_log", "duration_ms")
    op.drop_index("ix_personal_book_analyses_personal_book_id", table_name="personal_book_analyses")
    op.drop_index("ix_personal_book_analyses_user_id", table_name="personal_book_analyses")
    op.drop_table("personal_book_analyses")
    op.drop_index(
        "ix_personal_chapter_analyses_personal_book_id", table_name="personal_chapter_analyses"
    )
    op.drop_index("ix_personal_chapter_analyses_user_id", table_name="personal_chapter_analyses")
    op.drop_table("personal_chapter_analyses")
    op.drop_index("uq_personal_analysis_active_book", table_name="personal_analysis_tasks")
    op.drop_index("ix_personal_analysis_tasks_created_at", table_name="personal_analysis_tasks")
    op.drop_index("ix_personal_analysis_tasks_status", table_name="personal_analysis_tasks")
    op.drop_index(
        "ix_personal_analysis_tasks_personal_book_id", table_name="personal_analysis_tasks"
    )
    op.drop_index("ix_personal_analysis_tasks_user_id", table_name="personal_analysis_tasks")
    op.drop_table("personal_analysis_tasks")
