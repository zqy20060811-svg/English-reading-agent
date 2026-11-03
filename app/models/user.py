from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255))
    # 邮箱是否已验证：未验证允许正常使用，仅个人中心作提示（软校验不阻断登录）
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    # 管理员标记：可访问 /admin 后台接口（用户管理/书籍上下架/入库任务/AI 统计）
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    # 是否被禁用：禁用后立即无法登录（已有 token 由管理员禁用操作吊销）
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
