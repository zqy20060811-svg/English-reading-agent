"""个人中心服务层单元测试（不依赖数据库，用假 Repository 隔离）"""

import asyncio

import pytest
from fastapi import HTTPException

from app.core.security import hash_password
from app.models.user import User
from app.schemas.profile import PasswordChangeRequest, UserSettingsUpdateRequest
from app.services.profile_service import ProfileService


class FakeProfileRepo:
    def __init__(self, settings=None):
        self.settings = settings  # dict: {user_id: target_lang}
        self.upserted = None

    async def get_settings(self, user_id):
        lang = (self.settings or {}).get(user_id)
        if lang is None:
            return None
        return type("S", (), {"target_lang": lang})()

    async def upsert_settings(self, user_id, target_lang):
        self.upserted = (user_id, target_lang)
        return type("S", (), {"target_lang": target_lang})()


class FakeUserRepo:
    pass


def make_service(old_password="old12345", settings=None, committed=None):
    svc = ProfileService.__new__(ProfileService)  # 跳过 __init__，注入假依赖
    svc.repo = FakeProfileRepo(settings)
    svc.user_repo = FakeUserRepo()

    class FakeDB:
        async def commit(self):
            if committed is not None:
                committed.append(True)

    svc.db = FakeDB()
    user = User(username="u", email="u@e.com", hashed_password=hash_password(old_password))
    return svc, user


def test_change_password_wrong_old_password():
    svc, user = make_service()
    req = PasswordChangeRequest(old_password="wrongpw", new_password="newpass99")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(svc.change_password(user, req))
    assert exc.value.status_code == 400


def test_change_password_same_rejected():
    svc, user = make_service()
    req = PasswordChangeRequest(old_password="old12345", new_password="old12345")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(svc.change_password(user, req))
    assert exc.value.status_code == 400


def test_change_password_success():
    committed = []
    svc, user = make_service(committed=committed)
    req = PasswordChangeRequest(old_password="old12345", new_password="newpass99")
    asyncio.run(svc.change_password(user, req))
    assert committed == [True]  # 已提交
    # 新密码可校验通过，旧密码失效
    from app.core.security import verify_password
    assert verify_password("newpass99", user.hashed_password)
    assert not verify_password("old12345", user.hashed_password)


def test_settings_default_when_missing():
    svc, _ = make_service()
    assert asyncio.run(svc.get_settings(user_id=1)) == "中文"


def test_settings_update_returns_value():
    svc, _ = make_service()
    req = UserSettingsUpdateRequest(target_lang="English")
    assert asyncio.run(svc.update_settings(1, req)) == "English"
    assert svc.repo.upserted == (1, "English")


def test_history_rows_converted():
    svc = ProfileService.__new__(ProfileService)

    class Row:
        book_id, title, author = 2, "A Christmas Carol", "Charles Dickens"
        cover_url = "http://x/2.jpg"
        chapter_index, percent = 3, 45.0
        from datetime import datetime
        updated_at = datetime(2026, 11, 3)

    class FakeRepo:
        @staticmethod
        async def list_history(user_id, limit):
            return [Row()]

    svc.repo = FakeRepo()
    items = asyncio.run(svc.get_history(user_id=1, limit=20))
    assert len(items) == 1
    assert items[0].book_id == 2 and items[0].title == "A Christmas Carol"
    assert items[0].percent == 45.0
