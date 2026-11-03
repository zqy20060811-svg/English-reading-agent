"""入库任务防重：同书仅允许一个进行中任务（部分唯一索引）

- 迁移前先归位历史遗留的 running 任务（上次部署中断留下的卡死任务），
  避免归位前建索引因同书多行占用而失败
- 新增部分唯一索引 uq_ingest_tasks_active_book：
  同一 gutenberg_id 在 pending/running 状态下至多一行，跨进程并发提交的最终兜底

Revision ID: c7f2a9d4e613
Revises: a3f9c2d71e58
Create Date: 2026-11-03
"""

from alembic import op
import sqlalchemy as sa

revision = "c7f2a9d4e613"
down_revision = "a3f9c2d71e58"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1) 归位历史遗留的 running 任务：迁移在应用停机时执行，running 必为中断残留
    op.execute(
        sa.text(
            "UPDATE ingest_tasks SET status = 'failed', "
            "error = '服务升级/重启导致任务中断（迁移自动归位），可安全重试', "
            "finished_at = NOW() "
            "WHERE status = 'running'"
        )
    )
    # 2) 部分唯一索引：同一本书同时最多一个进行中任务
    op.create_index(
        "uq_ingest_tasks_active_book",
        "ingest_tasks",
        ["gutenberg_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_ingest_tasks_active_book", table_name="ingest_tasks")
