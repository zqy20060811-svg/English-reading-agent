"""生词本自定义分组：新表 vocabulary_groups + user_vocabulary.group_id

Revision ID: e5f8a63c94b2
Revises: c3a7b95e21f4
Create Date: 2026-11-05
"""

import sqlalchemy as sa
from alembic import op

revision = "e5f8a63c94b2"
down_revision = "c3a7b95e21f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vocabulary_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("user_id", "name", name="uq_vocabulary_group_user_name"),
    )
    op.add_column(
        "user_vocabulary",
        sa.Column("group_id", sa.Integer(), nullable=True),
    )
    op.create_index("ix_user_vocabulary_group_id", "user_vocabulary", ["group_id"])
    op.create_foreign_key(
        "fk_user_vocabulary_group_id",
        "user_vocabulary", "vocabulary_groups",
        ["group_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_user_vocabulary_group_id", "user_vocabulary", type_="foreignkey")
    op.drop_index("ix_user_vocabulary_group_id", table_name="user_vocabulary")
    op.drop_column("user_vocabulary", "group_id")
    op.drop_table("vocabulary_groups")
