import re
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

from app.core.config import get_settings

# 密码复杂度：至少 8 位且同时包含字母与数字
PASSWORD_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d).{8,64}$")


def validate_password_strength(password: str) -> str:
    """校验密码复杂度，不达标抛 ValueError（供 Pydantic field_validator 使用）"""
    if not PASSWORD_PATTERN.match(password):
        raise ValueError("密码至少 8 位，且需同时包含字母和数字")
    return password


def hash_password(plain: str) -> str:
    """bcrypt 加密密码"""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验明文密码与哈希是否匹配"""
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def create_access_token(user_id: int) -> str:
    """生成短时效 JWT（payload 带用户 ID、类型与过期时间）"""
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.JWT_ACCESS_EXPIRE_MINUTES)
    payload = {"sub": str(user_id), "type": "access", "exp": expire}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token() -> str:
    """生成不透明随机 Refresh Token（状态存 Redis，便于随时吊销）"""
    return secrets.token_urlsafe(48)


def get_access_ttl_seconds() -> int:
    """Access Token 有效期（秒），与 JWT 过期时间一致"""
    return get_settings().JWT_ACCESS_EXPIRE_MINUTES * 60


def get_refresh_ttl_seconds() -> int:
    """Refresh Token 有效期（秒）"""
    return get_settings().REFRESH_TOKEN_EXPIRE_DAYS * 86400


def decode_access_token(token: str) -> int | None:
    """解码 Access JWT，返回 user_id；无效、过期或类型不符返回 None"""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("type") != "access":
            return None
        return int(payload["sub"])
    except (jwt.PyJWTError, KeyError, ValueError):
        return None
