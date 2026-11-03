from fastapi import APIRouter, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.db.database import get_db
from app.schemas.user import (
    EmailRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserLoginRequest,
    UserOut,
    UserRegisterRequest,
    VerifyEmailRequest,
)
from app.services.user_service import UserService, get_current_user

router = APIRouter(prefix="/auth", tags=["认证"])
bearer_scheme = HTTPBearer()


class RefreshRequest(BaseModel):
    """刷新令牌请求体"""

    refresh_token: str = Field(min_length=1)


class LogoutRequest(BaseModel):
    """登出请求体（refresh_token 可选，便于一并吊销）"""

    refresh_token: str | None = None


@router.post("/register", response_model=UserOut, status_code=201)
async def register(req: UserRegisterRequest, db=Depends(get_db)):
    """注册新用户"""
    return await UserService(db).register(req)


@router.post("/login", response_model=TokenResponse)
async def login(req: UserLoginRequest, request: Request, db=Depends(get_db)):
    """登录，返回 access_token（30 分钟）+ refresh_token（7 天），双 token 同步存入 Redis db0。

    连续失败 5 次触发 15 分钟锁定（按 IP + 用户名计数）。
    """
    client_ip = request.client.host if request.client else "-"
    tokens = await UserService(db).login(req, client_ip)
    return TokenResponse(**tokens)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(req: RefreshRequest, db=Depends(get_db)):
    """用 refresh_token 换新 token 对（轮换旧 refresh 立即作废）"""
    tokens = await UserService(db).refresh(req.refresh_token)
    return TokenResponse(**tokens)


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db=Depends(get_db),
    req: LogoutRequest | None = None,
):
    """登出：删除 Redis 中的 access token，若携带 refresh_token 一并吊销"""
    refresh_token = req.refresh_token if req else None
    await UserService(db).logout(credentials.credentials, refresh_token)
    return {"detail": "登出成功"}


@router.post("/send-verification")
async def send_verification(req: EmailRequest, db=Depends(get_db)):
    """发送邮箱验证码（开发期无 SMTP 配置时验证码打印到后端控制台）"""
    await UserService(db).send_verification(req.email)
    return {"detail": "验证码已发送，请查收（开发环境见后端控制台）"}


@router.post("/verify-email")
async def verify_email(req: VerifyEmailRequest, db=Depends(get_db)):
    """校验邮箱验证码，标记邮箱为已验证"""
    await UserService(db).verify_email(req.email, req.code)
    return {"detail": "邮箱验证成功"}


@router.post("/forgot-password")
async def forgot_password(req: EmailRequest, db=Depends(get_db)):
    """发送密码找回验证码；无论邮箱是否注册均返回相同响应，不暴露注册情况"""
    await UserService(db).send_password_reset(req.email)
    return {"detail": "若该邮箱已注册，验证码已发送（开发环境见后端控制台）"}


@router.post("/reset-password")
async def reset_password(req: ResetPasswordRequest, db=Depends(get_db)):
    """凭邮箱验证码重置密码，成功后全部旧 token 失效"""
    await UserService(db).reset_password(req.email, req.code, req.new_password)
    return {"detail": "密码已重置，请使用新密码登录"}
