"""personal_books 增加 cover_ext 列（EPUB 内嵌封面扩展名，None=无封面）

Revision ID: c3a7b95e21f4
Revises: d8e4f2a91b73
Create Date: 2026-11-05
"""

from alembic import op
import sqlalchemy as sa

revision = "c3a7b95e21f4"
down_revision = "d8e4f2a91b73"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("personal_books", sa.Column("cover_ext", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("personal_books", "cover_ext")
