"""个人电子书：用户上传的私人阅读材料（与公共书库物理隔离）

新增三张独立表，不复用也不修改公共 books / book_chapters / book_chunks：
- personal_books：书籍元数据 + 原始文件路径 + 内容哈希（同人同文件唯一去重）
- personal_book_chapters：章节正文（(book_id, chapter_index) 唯一，随书级联删除）
- personal_reading_progress：阅读进度（(user_id, book_id) 唯一，随书级联删除）

Revision ID: e5b7c1a93d42
Revises: c7f2a9d4e613
Create Date: 2026-11-03
"""

from alembic import op
import sqlalchemy as sa

revision = "e5b7c1a93d42"
down_revision = "c7f2a9d4e613"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_books",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("author", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=16), nullable=False),
        sa.Column("source_type", sa.String(length=8), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_path", sa.String(length=512), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("chapter_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "content_sha256", name="uq_personal_book_user_hash"),
    )
    op.create_index("ix_personal_books_user_id", "personal_books", ["user_id"])
    op.create_index("ix_personal_books_created_at", "personal_books", ["created_at"])

    op.create_table(
        "personal_book_chapters",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("personal_book_id", sa.Integer(), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("word_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["personal_book_id"], ["personal_books.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "personal_book_id", "chapter_index", name="uq_personal_chapter_index"
        ),
    )
    op.create_index(
        "ix_personal_book_chapters_personal_book_id",
        "personal_book_chapters",
        ["personal_book_id"],
    )

    op.create_table(
        "personal_reading_progress",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("personal_book_id", sa.Integer(), nullable=False),
        sa.Column("chapter_index", sa.Integer(), nullable=False),
        sa.Column("char_offset", sa.Integer(), nullable=False),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("percent", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["personal_book_id"], ["personal_books.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "personal_book_id", name="uq_personal_progress_user_book"
        ),
    )
    op.create_index(
        "ix_personal_reading_progress_user_id", "personal_reading_progress", ["user_id"]
    )
    op.create_index(
        "ix_personal_reading_progress_personal_book_id",
        "personal_reading_progress",
        ["personal_book_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_personal_reading_progress_personal_book_id",
        table_name="personal_reading_progress",
    )
    op.drop_index(
        "ix_personal_reading_progress_user_id", table_name="personal_reading_progress"
    )
    op.drop_table("personal_reading_progress")
    op.drop_index(
        "ix_personal_book_chapters_personal_book_id", table_name="personal_book_chapters"
    )
    op.drop_table("personal_book_chapters")
    op.drop_index("ix_personal_books_created_at", table_name="personal_books")
    op.drop_index("ix_personal_books_user_id", table_name="personal_books")
    op.drop_table("personal_books")
