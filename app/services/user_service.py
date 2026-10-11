from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.database import get_db
from app.models.user import User
from app.repositories.token_repository import TokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserLoginRequest, UserRegisterRequest

bearer_scheme = HTTPBearer()


class UserService:
    """用户注册/登录业务逻辑"""

    def __init__(self, db: AsyncSession):
        self.repo = UserRepository(db)

    async def register(self, req: UserRegisterRequest) -> User:
        if await self.repo.get_by_username(req.username):
            raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被注册")
        if await self.repo.get_by_email(req.email):
            raise HTTPException(status.HTTP_409_CONFLICT, "邮箱已被注册")
        return await self.repo.create(req.username, req.email, hash_password(req.password))

    async def login(self, req: UserLoginRequest) -> str:
        user = await self.repo.get_by_username(req.username)
        # 统一报错信息，不暴露用户是否存在
        if not user or not verify_password(req.password, user.hashed_password):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
        token = create_access_token(user.id)
        # token 存入 Redis（2 号库），TTL 与 JWT 过期时间一致
        await TokenRepository(get_redis()).save(token, user.id)
        return token

    async def logout(self, token: str) -> None:
        """登出：从 Redis 删除 token，使其立即失效"""
        await TokenRepository(get_redis()).delete(token)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """依赖项：从 Authorization: Bearer <token> 解析当前用户"""
    token = credentials.credentials
    user_id = decode_access_token(token)
    if user_id is None:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "令牌无效或已过期",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # JWT 合法之外，还需在 Redis 中存在（登出后即失效）
    if not await TokenRepository(get_redis()).exists(token):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "令牌已登出或不存在",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user = await UserRepository(db).get_by_id(user_id)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在")
    return user
