"""认证安全基础单元测试：密码复杂度、JWT 生成与解码、Refresh Token 形态"""

import pytest
from pydantic import ValidationError

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_access_token,
    validate_password_strength,
)
from app.schemas.user import UserRegisterRequest


class TestPasswordStrength:
    def test_valid_password(self):
        assert validate_password_strength("abc12345") == "abc12345"

    def test_too_short_rejected(self):
        with pytest.raises(ValueError):
            validate_password_strength("ab12")

    def test_letters_only_rejected(self):
        with pytest.raises(ValueError):
            validate_password_strength("abcdefgh")

    def test_digits_only_rejected(self):
        with pytest.raises(ValueError):
            validate_password_strength("12345678")

    def test_register_schema_rejects_weak_password(self):
        with pytest.raises(ValidationError):
            UserRegisterRequest(username="tester", email="t@e.com", password="123456")

    def test_register_schema_accepts_strong_password(self):
        req = UserRegisterRequest(username="tester", email="t@e.com", password="pass1234")
        assert req.password == "pass1234"


class TestAccessToken:
    def test_roundtrip(self):
        token = create_access_token(42)
        assert decode_access_token(token) == 42

    def test_garbage_token_returns_none(self):
        assert decode_access_token("not-a-jwt") is None

    def test_refresh_token_is_opaque_and_unique(self):
        t1, t2 = create_refresh_token(), create_refresh_token()
        assert t1 != t2
        # 不透明 refresh token 不应被当作 access JWT 解码
        assert decode_access_token(t1) is None
