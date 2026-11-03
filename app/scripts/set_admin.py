"""将指定用户提升为管理员（供首次部署初始化后台账号）。

用法：
    python -m app.scripts.set_admin <用户名>            # 设为管理员
    python -m app.scripts.set_admin <用户名> --revoke   # 取消管理员
"""

import argparse
import asyncio

from sqlalchemy import select

from app.db.database import AsyncSessionLocal
from app.models.user import User


async def set_admin(username: str, revoke: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.username == username))
        user = result.scalar_one_or_none()
        if user is None:
            print(f"用户「{username}」不存在")
            raise SystemExit(1)
        user.is_admin = not revoke
        await db.commit()
        state = "已取消管理员" if revoke else "已设为管理员"
        print(f"用户「{username}」（id={user.id}）{state}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="设置/取消用户管理员权限")
    parser.add_argument("username", help="用户名")
    parser.add_argument("--revoke", action="store_true", help="取消管理员权限")
    args = parser.parse_args()
    asyncio.run(set_admin(args.username, args.revoke))
