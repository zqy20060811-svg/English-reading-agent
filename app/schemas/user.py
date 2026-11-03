from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.core.security import validate_password_strength


class UserRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=50)
    email: EmailStr
    password: str = Field(min_length=8, max_length=64)

    @field_validator("password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        """密码复杂度：至少 8 位且同时包含字母与数字"""
        return validate_password_strength(v)


class UserLoginRequest(BaseModel):
    username: str
    password: str


class EmailRequest(BaseModel):
    """邮箱类请求基体"""

    email: EmailStr


class VerifyEmailRequest(EmailRequest):
    """邮箱验证码校验请求"""

    code: str = Field(min_length=6, max_length=6)


class ResetPasswordRequest(VerifyEmailRequest):
    """密码找回请求：邮箱验证码 + 新密码"""

    new_password: str = Field(min_length=8, max_length=64)

    @field_validator("new_password")
    @classmethod
    def check_password_strength(cls, v: str) -> str:
        """新密码复杂度：至少 8 位且同时包含字母与数字"""
        return validate_password_strength(v)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: EmailStr
    email_verified: bool
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
