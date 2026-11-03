"""阶段4：管理员字段、书籍上下架、入库任务表、LLM 用量表

Revision ID: a3f9c2d71e58
Revises: b827246c0ba7
Create Date: 2026-11-03 20:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a3f9c2d71e58'
down_revision: Union[str, Sequence[str], None] = 'b827246c0ba7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # 用户表：管理员标记 + 禁用标记（已有行回填默认值，避免非空约束冲突）
    op.add_column('users', sa.Column('is_admin', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('users', sa.Column('is_disabled', sa.Boolean(), nullable=False, server_default=sa.false()))

    # 书籍表：上下架状态（默认全部上架，与历史行为一致）
    op.add_column('books', sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()))

    # 入库任务表
    op.create_table(
        'ingest_tasks',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('gutenberg_id', sa.Integer(), nullable=False),
        sa.Column('embed', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('status', sa.String(length=20), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_by', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['created_by'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_ingest_tasks_gutenberg_id', 'ingest_tasks', ['gutenberg_id'])
    op.create_index('ix_ingest_tasks_status', 'ingest_tasks', ['status'])
    op.create_index('ix_ingest_tasks_created_at', 'ingest_tasks', ['created_at'])

    # LLM 调用流水表（成本统计）
    op.create_table(
        'llm_usage_log',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('scene', sa.String(length=30), nullable=False),
        sa.Column('model', sa.String(length=50), nullable=False, server_default=''),
        sa.Column('prompt_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('completion_tokens', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_llm_usage_log_user_id', 'llm_usage_log', ['user_id'])
    op.create_index('ix_llm_usage_log_scene', 'llm_usage_log', ['scene'])
    op.create_index('ix_llm_usage_log_created_at', 'llm_usage_log', ['created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_llm_usage_log_created_at', table_name='llm_usage_log')
    op.drop_index('ix_llm_usage_log_scene', table_name='llm_usage_log')
    op.drop_index('ix_llm_usage_log_user_id', table_name='llm_usage_log')
    op.drop_table('llm_usage_log')

    op.drop_index('ix_ingest_tasks_created_at', table_name='ingest_tasks')
    op.drop_index('ix_ingest_tasks_status', table_name='ingest_tasks')
    op.drop_index('ix_ingest_tasks_gutenberg_id', table_name='ingest_tasks')
    op.drop_table('ingest_tasks')

    op.drop_column('books', 'is_active')
    op.drop_column('users', 'is_disabled')
    op.drop_column('users', 'is_admin')
