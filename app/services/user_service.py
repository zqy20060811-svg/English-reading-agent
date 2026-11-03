from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.db.database import get_db
from app.models.user import User
from app.repositories.token_repository import TokenRepository
from app.repositories.user_repository import UserRepository
from app.schemas.user import UserLoginRequest, UserRegisterRequest
from app.services import email_service
from app.services.email_service import TooFrequentError

bearer_scheme = HTTPBearer()


class UserService:
    """用户注册/登录业务逻辑"""

    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = UserRepository(db)

    async def register(self, req: UserRegisterRequest) -> User:
        if await self.repo.get_by_username(req.username):
            raise HTTPException(status.HTTP_409_CONFLICT, "用户名已被注册")
        if await self.repo.get_by_email(req.email):
            raise HTTPException(status.HTTP_409_CONFLICT, "邮箱已被注册")
        return await self.repo.create(req.username, req.email, hash_password(req.password))

    async def login(self, req: UserLoginRequest, client_ip: str = "-") -> dict:
        """登录成功签发 access + refresh 双 token；连续失败触发限流锁定"""
        settings = get_settings()
        redis = get_redis()
        # 登录失败限流：按 IP + 用户名计数，窗口期内达到上限则锁定
        fail_key = f"login_fail:{client_ip}:{req.username}"
        fails = int(await redis.get(fail_key) or 0)
        if fails >= settings.LOGIN_FAIL_LIMIT:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                "登录失败次数过多，请 15 分钟后再试",
            )
        user = await self.repo.get_by_username(req.username)
        # 统一报错信息，不暴露用户是否存在
        if not user or not verify_password(req.password, user.hashed_password):
            await redis.incr(fail_key)
            await redis.expire(fail_key, settings.LOGIN_FAIL_WINDOW_SECONDS)
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户名或密码错误")
        await redis.delete(fail_key)  # 登录成功清零失败计数
        repo = TokenRepository(redis)
        access_token = create_access_token(user.id)
        refresh_token = create_refresh_token()
        # 双 token 同步存入 Redis（db0），access TTL 30 分钟、refresh TTL 7 天
        await repo.save(access_token, user.id)
        await repo.save_refresh(refresh_token, user.id)
        return {"access_token": access_token, "refresh_token": refresh_token}

    async def refresh(self, refresh_token: str) -> dict:
        """用 refresh token 换新 token 对（轮换：旧 refresh 立即作废）"""
        repo = TokenRepository(get_redis())
        user_id = await repo.get_refresh_user_id(refresh_token)
        if user_id is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "刷新令牌无效或已过期")
        await repo.delete_refresh(refresh_token)
        access_token = create_access_token(user_id)
        new_refresh_token = create_refresh_token()
        await repo.save(access_token, user_id)
        await repo.save_refresh(new_refresh_token, user_id)
        return {"access_token": access_token, "refresh_token": new_refresh_token}

    async def logout(self, token: str, refresh_token: str | None = None) -> None:
        """登出：删除 access token；若随请求携带 refresh token 一并吊销"""
        repo = TokenRepository(get_redis())
        await repo.delete(token)
        if refresh_token:
            await repo.delete_refresh(refresh_token)

    async def revoke_user_tokens(self, user_id: int) -> None:
        """吊销某用户全部 token（改密时调用，强制重新登录）"""
        repo = TokenRepository(get_redis())
        await repo.revoke_all_for_user(user_id)
        await repo.revoke_all_refresh_for_user(user_id)

    # ---------- 邮箱验证与密码找回 ----------

    async def send_verification(self, email: str) -> str:
        """发送邮箱验证码；邮箱未注册或已验证时报错"""
        user = await self.repo.get_by_email(email)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "该邮箱未注册")
        if user.email_verified:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "该邮箱已验证过")
        code = email_service.generate_code()
        try:
            await email_service.send_code(email, code, "verify", get_redis())
        except TooFrequentError:
            raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "发送过于频繁，请 1 分钟后再试")
        return code  # 开发环境 console 模式下便于联调；SMTP 模式该返回值不外显

    async def verify_email(self, email: str, code: str) -> None:
        """校验验证码并标记邮箱已验证"""
        if not await email_service.verify_code(email, code, "verify", get_redis()):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误或已过期")
        user = await self.repo.get_by_email(email)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "该邮箱未注册")
        user.email_verified = True
        await self.db.commit()

    async def send_password_reset(self, email: str) -> None:
        """发送密码找回验证码；邮箱不存在时静默成功，不暴露注册情况"""
        user = await self.repo.get_by_email(email)
        if user is not None:
            code = email_service.generate_code()
            try:
                await email_service.send_code(email, code, "reset", get_redis())
            except TooFrequentError:
                raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "发送过于频繁，请 1 分钟后再试")

    async def reset_password(self, email: str, code: str, new_password: str) -> None:
        """校验验证码后重置密码，并吊销该用户全部 token"""
        if not await email_service.verify_code(email, code, "reset", get_redis()):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误或已过期")
        user = await self.repo.get_by_email(email)
        if user is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "该邮箱未注册")
        user.hashed_password = hash_password(new_password)
        await self.db.commit()
        await self.revoke_user_tokens(user.id)


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
