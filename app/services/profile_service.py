"""个人中心业务逻辑：统计概览、阅读历史、修改密码、偏好设置"""

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User
from app.repositories.profile_repository import ProfileRepository
from app.repositories.user_repository import UserRepository
from app.schemas.profile import (
    HistoryItemOut,
    PasswordChangeRequest,
    UserSettingsUpdateRequest,
)
from app.services.user_service import UserService


class ProfileService:
    """个人中心业务层"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ProfileRepository(db)
        self.user_repo = UserRepository(db)

    async def get_stats(self, user_id: int) -> dict:
        """统计概览（读查询直接透传）"""
        return await self.repo.get_stats(user_id)

    async def get_history(self, user_id: int, limit: int) -> list[HistoryItemOut]:
        """最近阅读历史，转输出模型"""
        rows = await self.repo.list_history(user_id, limit)
        return [
            HistoryItemOut(
                book_id=r.book_id,
                title=r.title,
                author=r.author,
                cover_url=r.cover_url,
                chapter_index=r.chapter_index,
                percent=r.percent,
                updated_at=r.updated_at,
            )
            for r in rows
        ]

    async def change_password(self, user: User, req: PasswordChangeRequest) -> None:
        """校验旧密码后更新；成功后吊销该用户全部 token，强制重新登录"""
        if not verify_password(req.old_password, user.hashed_password):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "旧密码不正确")
        if req.old_password == req.new_password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "新密码不能与旧密码相同")
        user.hashed_password = hash_password(req.new_password)
        await self.db.commit()
        # 改密后旧 access/refresh token 全部失效，防止密码泄露后仍可继续访问
        await UserService(self.db).revoke_user_tokens(user.id)

    async def get_settings(self, user_id: int) -> str:
        """读取偏好；未设置过返回默认目标语言"""
        setting = await self.repo.get_settings(user_id)
        return setting.target_lang if setting else "中文"

    async def update_settings(self, user_id: int, req: UserSettingsUpdateRequest) -> str:
        """更新偏好（upsert），返回生效后的值"""
        setting = await self.repo.upsert_settings(user_id, req.target_lang)
        return setting.target_lang
