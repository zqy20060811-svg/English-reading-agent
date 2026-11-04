"""个人书籍生词收录：user_vocabulary.book_id 允许为空（阶段D）"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e4f2a91b73'
down_revision: Union[str, Sequence[str], None] = 'a9d2f4c7b618'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """个人书籍阅读也可收录生词：book_id 置空表示来源为个人书"""
    op.alter_column('user_vocabulary', 'book_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """回滚前需先清理 book_id 为空的生词条目"""
    op.execute("DELETE FROM user_vocabulary WHERE book_id IS NULL")
    op.alter_column('user_vocabulary', 'book_id', existing_type=sa.Integer(), nullable=False)
