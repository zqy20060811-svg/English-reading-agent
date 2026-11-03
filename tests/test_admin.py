"""阶段4后台管理测试。

- TestCostEstimate：成本估算纯单元（始终运行）
- TestAdminDB：下架书籍可见性（需要本地 PostgreSQL，缺失自动跳过）
- TestAdminHTTP：管理员权限 / 用户禁用 / 上下架 / 任务接口（需要后端运行中，不可达自动跳过）

运行：python -m pytest tests/test_admin.py -v
"""

import asyncio
import uuid

import pytest
import requests as http_requests
from fastapi import HTTPException
from sqlalchemy import select

from app.services.usage_service import estimate_cost_usd

BASE = "http://127.0.0.1:8002"


# ================= 成本估算（纯单元） =================


class TestCostEstimate:
    def test_zero_tokens_zero_cost(self):
        assert estimate_cost_usd(0, 0) == 0

    def test_million_input_tokens(self):
        # 1M 输入 tokens：0.27 美元/百万
        assert estimate_cost_usd(1_000_000, 0) == 0.27

    def test_mixed_usage(self):
        # 0.5M 输入 + 1M 输出 = 0.135 + 1.10
        assert estimate_cost_usd(500_000, 1_000_000) == 1.235


# ================= 数据库测试（需要 PostgreSQL） =================


def _db_available() -> bool:
    async def _ping():
        from app.db.database import engine

        await engine.dispose()  # 丢弃上个事件循环遗留的连接池，避免跨循环复用报错
        async with engine.connect() as conn:
            await conn.execute(select(1))

    try:
        asyncio.run(_ping())
        return True
    except Exception:
        return False


DB_READY = _db_available()
requires_db = pytest.mark.skipif(not DB_READY, reason="PostgreSQL 不可用，跳过数据库测试")


def _run(coro):
    async def _wrap():
        from app.db.database import engine

        await engine.dispose()
        await coro

    return asyncio.run(_wrap())


@requires_db
class TestAdminDB:
    def test_deactivated_book_hidden_and_chapter_404(self):
        """下架书籍：书库列表不可见、章节接口 404，上架后恢复"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.book import Book
            from app.services.book_service import BookService

            suffix = uuid.uuid4().hex[:8]
            async with AsyncSessionLocal() as db:
                book = Book(
                    gutenberg_id=900000 + int(suffix[:4], 16) % 90000,
                    title=f"AdminTest {suffix}",
                    author="tester",
                    year=2000,
                    genre="test",
                    synopsis="",
                    language="en",
                    source_url="http://test",
                    word_count=1000,
                    is_active=False,
                )
                db.add(book)
                await db.commit()
                await db.refresh(book)
                book_id = book.id
            try:
                svc = BookService(AsyncSessionLocal())
                titles = [b.title for b in await svc.list_all(limit=500)]
                assert f"AdminTest {suffix}" not in titles  # 下架书不出现在书库

                from fastapi import HTTPException as HE

                with pytest.raises(HE) as e:
                    await svc.get_chapter(book_id, 1)
                assert e.value.status_code == 404
                assert "已下架" in e.value.detail

                # 重新上架后章节接口恢复正常报「不存在第 N 章」而非「已下架」
                async with AsyncSessionLocal() as db:
                    b = await db.get(Book, book_id)
                    b.is_active = True
                    await db.commit()
                with pytest.raises(HE) as e:
                    await svc.get_chapter(book_id, 1)
                assert "已下架" not in e.value.detail
            finally:
                async with AsyncSessionLocal() as db:
                    b = await db.get(Book, book_id)
                    if b:
                        await db.delete(b)
                        await db.commit()

        _run(main())


# ================= HTTP 集成（需要后端运行中） =================


def _backend_up() -> bool:
    try:
        http_requests.get(f"{BASE}/docs", timeout=3)
        return True
    except Exception:
        return False


requires_backend = pytest.mark.skipif(not _backend_up(), reason="后端未运行，跳过 HTTP 集成测试")


def _register_and_login() -> tuple[str, int, str]:
    """注册一个新用户并登录，返回 (access_token, user_id, username)"""
    suffix = uuid.uuid4().hex[:8]
    username = f"admtest_{suffix}"
    resp = http_requests.post(
        f"{BASE}/auth/register",
        json={"username": username, "email": f"{username}@example.com", "password": "abc12345"},
        timeout=10,
    )
    assert resp.status_code in (200, 201), resp.text
    user_id = resp.json()["id"]
    resp = http_requests.post(
        f"{BASE}/auth/login", json={"username": username, "password": "abc12345"}, timeout=10
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"], user_id, username


def _promote_admin(user_id: int) -> None:
    """测试辅助：直接置 is_admin（绕过 API，仅测试环境用）"""
    _run(_set_user_flag(user_id, "is_admin", True))


def _undisable(user_id: int) -> None:
    _run(_set_user_flag(user_id, "is_disabled", False))


async def _set_user_flag(user_id: int, field: str, value: bool) -> None:
    from app.db.database import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        setattr(user, field, value)
        await db.commit()


@requires_db
@requires_backend
class TestAdminHTTP:
    def test_non_admin_forbidden(self):
        """普通用户访问后台接口必须 403"""
        token, _uid, _ = _register_and_login()
        r = http_requests.get(
            f"{BASE}/admin/users", headers={"Authorization": f"Bearer {token}"}, timeout=10
        )
        assert r.status_code == 403
        r = http_requests.get(
            f"{BASE}/admin/stats/ai", headers={"Authorization": f"Bearer {token}"}, timeout=10
        )
        assert r.status_code == 403

    def test_admin_overview_and_users(self):
        """管理员可查概览与用户列表"""
        token, uid, username = _register_and_login()
        _promote_admin(uid)
        h = {"Authorization": f"Bearer {token}"}
        r = http_requests.get(f"{BASE}/admin/overview", headers=h, timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["total_users"] >= 1
        assert data["total_books"] >= data["active_books"]

        r = http_requests.get(f"{BASE}/admin/users?query={username}", headers=h, timeout=10)
        assert r.status_code == 200
        users = r.json()
        assert any(u["id"] == uid for u in users)
        assert users[0]["is_admin"] is True  # AdminUserOut 含 is_admin 字段

    def test_disable_user_blocks_login(self):
        """禁用用户：已签发 token 立即失效、无法重新登录，解禁后恢复；不能禁用自己"""
        token, uid, username = _register_and_login()
        _promote_admin(uid)
        h = {"Authorization": f"Bearer {token}"}

        # 防呆：管理员不能禁用/取消自己的管理员权限
        r = http_requests.patch(f"{BASE}/admin/users/{uid}", headers=h, json={"is_disabled": True}, timeout=10)
        assert r.status_code == 400
        r = http_requests.patch(f"{BASE}/admin/users/{uid}", headers=h, json={"is_admin": False}, timeout=10)
        assert r.status_code == 400

        # 注册一个普通用户作为禁用目标
        target_token, target_uid, target_name = _register_and_login()
        r = http_requests.patch(
            f"{BASE}/admin/users/{target_uid}", headers=h, json={"is_disabled": True}, timeout=10
        )
        assert r.status_code == 200 and r.json()["is_disabled"] is True

        # 目标用户已签发 token 立即失效（禁用即吊销全部 token：401 token 不存在）
        th = {"Authorization": f"Bearer {target_token}"}
        r = http_requests.get(f"{BASE}/me", headers=th, timeout=10)
        assert r.status_code in (401, 403)

        # 重新登录也被拒绝（403 账号禁用，而非 401 密码错误）
        r = http_requests.post(
            f"{BASE}/auth/login", json={"username": target_name, "password": "abc12345"}, timeout=10
        )
        assert r.status_code == 403
        assert "禁用" in r.json()["detail"]

        # 解禁后可重新登录
        r = http_requests.patch(
            f"{BASE}/admin/users/{target_uid}", headers=h, json={"is_disabled": False}, timeout=10
        )
        assert r.status_code == 200
        r = http_requests.post(
            f"{BASE}/auth/login", json={"username": target_name, "password": "abc12345"}, timeout=10
        )
        assert r.status_code == 200

    def test_book_toggle_active(self):
        """上下架：PATCH 后书库列表同步隐藏/恢复"""
        token, uid, _ = _register_and_login()
        _promote_admin(uid)
        h = {"Authorization": f"Bearer {token}"}
        # 取任一上架书
        books = http_requests.get(f"{BASE}/books", headers=h, timeout=10).json()
        book = books[0]
        r = http_requests.patch(
            f"{BASE}/admin/books/{book['id']}", headers=h, json={"is_active": False}, timeout=10
        )
        assert r.status_code == 200 and r.json()["is_active"] is False
        visible = {b["id"] for b in http_requests.get(f"{BASE}/books", headers=h, timeout=10).json()}
        assert book["id"] not in visible

        # 恢复上架
        r = http_requests.patch(
            f"{BASE}/admin/books/{book['id']}", headers=h, json={"is_active": True}, timeout=10
        )
        assert r.status_code == 200
        visible = {b["id"] for b in http_requests.get(f"{BASE}/books", headers=h, timeout=10).json()}
        assert book["id"] in visible

    def test_task_retry_validation(self):
        """任务接口：重试不存在任务 404；AI 统计接口返回结构完整"""
        token, uid, _ = _register_and_login()
        _promote_admin(uid)
        h = {"Authorization": f"Bearer {token}"}
        r = http_requests.post(f"{BASE}/admin/ingest/tasks/999999999/retry", headers=h, timeout=10)
        assert r.status_code == 404

        r = http_requests.get(f"{BASE}/admin/stats/ai?days=7", headers=h, timeout=10)
        assert r.status_code == 200
        data = r.json()
        assert data["days"] == 7
        assert isinstance(data["by_scene"], list) and isinstance(data["by_day"], list)


async def _undisable(user_id: int) -> None:
    from app.db.database import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        user.is_disabled = False
        await db.commit()
