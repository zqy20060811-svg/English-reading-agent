"""个人中心路由：统计概览 / 阅读历史 / 修改密码 / 偏好设置（均需登录）"""

from fastapi import APIRouter, Depends, Query

from app.db.database import get_db
from app.models.user import User
from app.schemas.profile import (
    HistoryItemOut,
    PasswordChangeRequest,
    UserSettingsOut,
    UserSettingsUpdateRequest,
    UserStatsOut,
)
from app.schemas.user import UserOut
from app.services.profile_service import ProfileService
from app.services.user_service import get_current_user

router = APIRouter(prefix="/me", tags=["个人中心"])


@router.get("", response_model=UserOut)
async def my_profile(current_user: User = Depends(get_current_user)):
    """当前登录用户信息（前端据此显示「管理后台」入口等）"""
    return current_user


async def get_profile_service(
    db=Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> tuple[ProfileService, User]:
    """构造服务并透传当前用户（token 认证复用 get_current_user）"""
    return ProfileService(db), current_user


@router.get("/stats", response_model=UserStatsOut)
async def my_stats(service_user=Depends(get_profile_service)):
    """个人中心统计：读过的书 / 章节数 / 点赞 / 收藏 / 翻译次数与字符 / 英语等级"""
    service, user = service_user
    return await service.get_stats(user.id)


@router.get("/history", response_model=list[HistoryItemOut])
async def my_history(
    limit: int = Query(default=20, ge=1, le=50),
    service_user=Depends(get_profile_service),
):
    """最近阅读历史（含书籍信息与进度，按更新时间倒序）"""
    service, user = service_user
    return await service.get_history(user.id, limit)


@router.put("/password")
async def change_password(
    req: PasswordChangeRequest,
    service_user=Depends(get_profile_service),
):
    """修改密码：校验旧密码，成功后前端需重新登录"""
    service, user = service_user
    await service.change_password(user, req)
    return {"detail": "密码修改成功，请重新登录"}


@router.get("/settings", response_model=UserSettingsOut)
async def get_settings(service_user=Depends(get_profile_service)):
    """读取偏好设置（未设置过返回默认值）"""
    service, user = service_user
    return UserSettingsOut(target_lang=await service.get_settings(user.id))


@router.put("/settings", response_model=UserSettingsOut)
async def update_settings(
    req: UserSettingsUpdateRequest,
    service_user=Depends(get_profile_service),
):
    """更新偏好设置（当前支持翻译默认目标语言）"""
    service, user = service_user
    target_lang = await service.update_settings(user.id, req)
    return UserSettingsOut(target_lang=target_lang)
