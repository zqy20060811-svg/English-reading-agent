"""核心业务稳定性测试。

三部分，按外部依赖自动降级：
- TestLLMFailure：AI 请求超时 / 接口报错 / 空响应的异常映射（纯单元，始终运行）
- TestQuota：每用户每日配额限流（纯单元，始终运行）
- TestDBStability：并发进度保存 / 并发生词与书签幂等 / 多用户数据隔离
  （需要本地 PostgreSQL，缺失时自动跳过；测试数据用完即清理）
- TestAuthFlowHTTP：注册→登录→刷新轮换→登出完整链路（需要后端运行中，不可达自动跳过）

运行：python -m pytest tests/test_stability.py -v
"""

import asyncio
import uuid
from datetime import date

import pytest
import requests as http_requests
from fastapi import HTTPException
from sqlalchemy import delete, func, select

from app.core.security import hash_password
from app.schemas.study import BookmarkAddRequest, VocabularyAddRequest
from app.services.llm_service import LLMService
from app.services.quota_service import QuotaExceededError, check_daily_quota

# ================= AI 请求异常映射 =================


class TestLLMFailure:
    """DeepSeek 调用失败时必须映射为 502/400，而不是泄漏原始异常"""

    def test_timeout_maps_to_502(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise http_requests.Timeout("timed out")

        monkeypatch.setattr("app.services.llm_service.requests.post", _boom)
        with pytest.raises(HTTPException) as e:
            asyncio.run(LLMService().ask("问题"))
        assert e.value.status_code == 502
        assert "无法连接" in e.value.detail

    def test_connection_error_maps_to_502(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise http_requests.ConnectionError("refused")

        monkeypatch.setattr("app.services.llm_service.requests.post", _boom)
        with pytest.raises(HTTPException) as e:
            asyncio.run(LLMService().ask("问题"))
        assert e.value.status_code == 502

    def test_http_error_maps_to_502_with_truncated_detail(self, monkeypatch):
        resp = http_requests.Response()
        resp.status_code = 502
        resp._content = b"upstream busy"
        resp.url = "http://test"

        def _boom(*args, **kwargs):
            raise http_requests.HTTPError(response=resp)

        monkeypatch.setattr("app.services.llm_service.requests.post", _boom)
        with pytest.raises(HTTPException) as e:
            asyncio.run(LLMService().ask("问题"))
        assert e.value.status_code == 502
        assert "DeepSeek 接口错误" in e.value.detail

    def test_empty_answer_maps_to_502(self, monkeypatch):
        """DeepSeek 正常返回但内容为空：必须 502，不能把空串当答案"""

        class FakeResp:
            def raise_for_status(self):
                return None

            def json(self):
                return {"choices": [{"message": {"content": "   "}}]}

        def _fake_post(*args, **kwargs):
            return FakeResp()

        monkeypatch.setattr(
            "app.services.llm_service.requests.post", _fake_post
        )
        with pytest.raises(HTTPException) as e:
            LLMService._request_chat({"messages": []})
        assert e.value.status_code == 502
        assert "返回内容为空" in e.value.detail

    def test_empty_context_rejected_before_llm_call(self):
        with pytest.raises(HTTPException) as e:
            asyncio.run(LLMService().ask_with_context("问题", ""))
        assert e.value.status_code == 400

    def test_rewrite_failure_falls_back_to_original(self, monkeypatch):
        """查询改写失败不得阻塞检索主链路，必须回退原始问题"""

        def _boom(*args, **kwargs):
            raise http_requests.Timeout("timed out")

        monkeypatch.setattr("app.services.llm_service.requests.post", _boom)
        out = asyncio.run(LLMService().rewrite_query("爱丽丝掉进什么洞？"))
        assert out == "爱丽丝掉进什么洞？"


# ================= 每日配额限流 =================


class FakeRedis:
    """最小 Redis 桩：incr / get / expire"""

    def __init__(self):
        self.store: dict[str, int] = {}

    async def incr(self, key):
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def get(self, key):
        return self.store.get(key)

    async def expire(self, key, ttl):
        return None


class TestQuota:
    def test_within_quota_passes(self):
        redis = FakeRedis()
        for i in range(3):
            used = asyncio.run(check_daily_quota(1, "AI 问答", 5, redis))
            assert used == i + 1

    def test_over_quota_raises(self):
        redis = FakeRedis()
        key_day = date.today().isoformat()
        with pytest.raises(QuotaExceededError):
            for _ in range(6):
                asyncio.run(check_daily_quota(1, "AI 问答", 5, redis))
        assert redis.store[f"quota:AI 问答:1:{key_day}"] == 6

    def test_quota_scoped_by_user_and_scene(self):
        """不同用户 / 场景计数互不干扰"""
        redis = FakeRedis()
        asyncio.run(check_daily_quota(1, "翻译", 1, redis))
        asyncio.run(check_daily_quota(2, "翻译", 1, redis))
        asyncio.run(check_daily_quota(1, "AI 问答", 1, redis))
        # 三个 key 各自为 1，互不挤占
        assert all(v == 1 for v in redis.store.values())


# ================= 数据库稳定性（需要 PostgreSQL） =================

def _db_available() -> bool:
    async def _ping():
        from app.db.database import engine

        async with engine.connect() as conn:
            await conn.execute(select(1))

    try:
        asyncio.run(_ping())
        return True
    except Exception:
        return False


DB_READY = _db_available()

requires_db = pytest.mark.skipif(not DB_READY, reason="PostgreSQL 不可用，跳过数据库稳定性测试")


def _run(coro):
    """在每个用例前丢弃上个事件循环遗留的连接池，避免跨循环复用报错"""
    async def _wrap():
        from app.db.database import engine

        await engine.dispose()
        await coro

    return asyncio.run(_wrap())


async def _make_user(tag: str):
    """创建测试用户（数据隔离用），返回 user id"""
    from app.db.database import AsyncSessionLocal
    from app.models.user import User

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            username=f"stab_{tag}_{suffix}",
            email=f"stab_{tag}_{suffix}@example.com",
            hashed_password=hash_password("abc12345"),
        )
        db.add(user)
        await db.commit()
        return user.id


async def _cleanup_users(user_ids: list[int]):
    """删除测试用户及其全部业务数据（外键无级联，需按依赖顺序删除）"""
    from app.db.database import AsyncSessionLocal
    from app.models.book_interaction import BookInteraction
    from app.models.reading_progress import UserReadingProgress
    from app.models.user import User
    from app.models.user_bookmark import UserBookmark
    from app.models.user_vocabulary import UserVocabulary

    async with AsyncSessionLocal() as db:
        for uid in user_ids:
            await db.execute(delete(UserVocabulary).where(UserVocabulary.user_id == uid))
            await db.execute(delete(UserBookmark).where(UserBookmark.user_id == uid))
            await db.execute(delete(UserReadingProgress).where(UserReadingProgress.user_id == uid))
            await db.execute(delete(BookInteraction).where(BookInteraction.user_id == uid))
            await db.execute(delete(User).where(User.id == uid))
        await db.commit()


async def _any_book_id() -> int:
    from app.db.database import AsyncSessionLocal
    from app.models.book import Book

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.min(Book.id)))
        return int(result.scalar_one())


@requires_db
class TestDBStability:
    """并发写入与多用户隔离（真实 PostgreSQL）"""

    def test_concurrent_first_save_progress_single_row(self):
        """并发首次保存进度：只允许产生一行，且不抛异常（原「先查后插」会唯一约束冲突 500）"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.reading_progress import UserReadingProgress
            from app.repositories.reading_progress_repository import ReadingProgressRepository

            uid = await _make_user("prog")
            book_id = await _any_book_id()
            try:
                async def save(i: int):
                    async with AsyncSessionLocal() as db:
                        await ReadingProgressRepository(db).upsert(
                            uid, book_id, chapter_index=i, char_offset=i * 10,
                            percent=float(i), page_index=i,
                        )

                await asyncio.gather(*(save(i) for i in range(8)))
                async with AsyncSessionLocal() as db:
                    count = (await db.execute(
                        select(func.count()).select_from(UserReadingProgress)
                        .where(UserReadingProgress.user_id == uid)
                    )).scalar_one()
                assert count == 1
            finally:
                await _cleanup_users([uid])

        _run(main())

    def test_concurrent_update_progress_final_state_valid(self):
        """并发更新同一行：全部成功，最终值必为某一次写入的合法值"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.repositories.reading_progress_repository import ReadingProgressRepository

            uid = await _make_user("progu")
            book_id = await _any_book_id()
            try:
                async with AsyncSessionLocal() as db:
                    await ReadingProgressRepository(db).upsert(uid, book_id, 0, 0, 0.0, 0)

                async def save(i: int):
                    async with AsyncSessionLocal() as db:
                        await ReadingProgressRepository(db).upsert(
                            uid, book_id, chapter_index=i, char_offset=i,
                            percent=float(i), page_index=i,
                        )

                await asyncio.gather(*(save(i) for i in range(6)))
                from app.models.reading_progress import UserReadingProgress

                async with AsyncSessionLocal() as db:
                    row = (await db.execute(
                        select(UserReadingProgress)
                        .where(UserReadingProgress.user_id == uid)
                    )).scalar_one()
                assert row.chapter_index in range(6)
                assert row.page_index == row.chapter_index
            finally:
                await _cleanup_users([uid])

        _run(main())

    def test_concurrent_add_same_word_idempotent(self):
        """并发生词收录同一词：唯一约束兜底，只产生一行，全部请求成功返回"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.user_vocabulary import UserVocabulary
            from app.repositories.vocabulary_repository import VocabularyRepository

            uid = await _make_user("vocab")
            book_id = await _any_book_id()
            try:
                async def add(i: int):
                    async with AsyncSessionLocal() as db:
                        row = await VocabularyRepository(db).add(
                            uid, book_id, "rabbit", chapter_index=1,
                            context_sentence=f"ctx {i}",
                        )
                        assert row is not None
                        return row.id

                ids = await asyncio.gather(*(add(i) for i in range(6)))
                assert len(set(ids)) == 1  # 全部返回同一条
                async with AsyncSessionLocal() as db:
                    count = (await db.execute(
                        select(func.count()).select_from(UserVocabulary)
                        .where(UserVocabulary.user_id == uid)
                    )).scalar_one()
                assert count == 1
            finally:
                await _cleanup_users([uid])

        _run(main())

    def test_concurrent_add_same_bookmark_idempotent(self):
        """并发添加同一位置书签：只产生一行，全部请求成功"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.user_bookmark import UserBookmark
            from app.repositories.bookmark_repository import BookmarkRepository

            uid = await _make_user("bm")
            book_id = await _any_book_id()
            try:
                async def add(i: int):
                    async with AsyncSessionLocal() as db:
                        row = await BookmarkRepository(db).add(
                            uid, book_id, chapter_index=2, page_index=5,
                            excerpt=f"ex {i}",
                        )
                        assert row is not None
                        return row.id

                ids = await asyncio.gather(*(add(i) for i in range(6)))
                assert len(set(ids)) == 1
                async with AsyncSessionLocal() as db:
                    count = (await db.execute(
                        select(func.count()).select_from(UserBookmark)
                        .where(UserBookmark.user_id == uid)
                    )).scalar_one()
                assert count == 1
            finally:
                await _cleanup_users([uid])

        _run(main())

    def test_concurrent_first_toggle_like_no_error(self):
        """并发首次点赞同一本书：原子插入兜底，不抛唯一约束异常，状态一致"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.repositories.book_interaction_repository import BookInteractionRepository

            uid = await _make_user("like")
            book_id = await _any_book_id()
            try:
                async def toggle(_: int):
                    async with AsyncSessionLocal() as db:
                        return await BookInteractionRepository(db).toggle(book_id, uid, "like")

                results = await asyncio.gather(*(toggle(i) for i in range(4)))
                assert all(isinstance(r, bool) for r in results)
            finally:
                await _cleanup_users([uid])

        _run(main())

    def test_multi_user_isolation(self):
        """多用户隔离：B 看不到 / 删不掉 A 的生词、书签、进度"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.repositories.bookmark_repository import BookmarkRepository
            from app.repositories.reading_progress_repository import ReadingProgressRepository
            from app.repositories.vocabulary_repository import VocabularyRepository

            uid_a = await _make_user("isoA")
            uid_b = await _make_user("isoB")
            book_id = await _any_book_id()
            try:
                # A 写入三类数据
                async with AsyncSessionLocal() as db:
                    vocab = await VocabularyRepository(db).add(uid_a, book_id, "wonder", 1, None)
                    bm = await BookmarkRepository(db).add(uid_a, book_id, 1, 0, "ex")
                    await ReadingProgressRepository(db).upsert(uid_a, book_id, 3, 100, 10.0, 2)
                    vocab_id, bm_id = vocab.id, bm.id

                # B 的列表全部为空
                async with AsyncSessionLocal() as db:
                    assert await VocabularyRepository(db).list_by_user(uid_b) == []
                    assert await BookmarkRepository(db).list_by_user(uid_b) == []
                    assert await ReadingProgressRepository(db).get(uid_b, book_id) is None

                # B 按 id 删 A 的资源：受 user_id 过滤保护，删不掉
                async with AsyncSessionLocal() as db:
                    assert await VocabularyRepository(db).remove(uid_b, vocab_id) == 0
                    assert await BookmarkRepository(db).remove(uid_b, bm_id) == 0

                # A 的数据未被破坏
                async with AsyncSessionLocal() as db:
                    assert len(await VocabularyRepository(db).list_by_user(uid_a)) == 1
                    assert len(await BookmarkRepository(db).list_by_user(uid_a)) == 1
                    assert (await ReadingProgressRepository(db).get(uid_a, book_id)).chapter_index == 3
            finally:
                await _cleanup_users([uid_a, uid_b])

        _run(main())


# ================= 认证完整链路（需要后端运行中） =================

BASE_URL = "http://127.0.0.1:8002"


def _backend_up() -> bool:
    try:
        http_requests.get(f"{BASE_URL}/docs", timeout=2)
        return True
    except Exception:
        return False


requires_backend = pytest.mark.skipif(not _backend_up(), reason="后端未运行，跳过 HTTP 链路测试")


@requires_backend
class TestAuthFlowHTTP:
    """注册 → 登录 → 刷新轮换 → 登出 → 重新登录 完整链路"""

    def setup_method(self):
        suffix = uuid.uuid4().hex[:8]
        self.username = f"stabflow_{suffix}"
        self.email = f"stabflow_{suffix}@example.com"
        self.password = "abc12345"

    def _register(self):
        return http_requests.post(
            f"{BASE_URL}/auth/register", timeout=10,
            json={"username": self.username, "email": self.email, "password": self.password},
        )

    def _login(self, password=None):
        return http_requests.post(
            f"{BASE_URL}/auth/login", timeout=10,
            json={"username": self.username, "password": password or self.password},
        )

    def test_full_auth_lifecycle(self):
        # 注册
        r = self._register()
        assert r.status_code == 201, r.text
        # 重复注册被拒绝
        assert self._register().status_code in (400, 409)
        # 登录拿双 token
        r = self._login()
        assert r.status_code == 200, r.text
        tokens = r.json()
        access, refresh = tokens["access_token"], tokens["refresh_token"]
        # access 可用
        r = http_requests.get(f"{BASE_URL}/me", headers={"Authorization": f"Bearer {access}"}, timeout=10)
        assert r.status_code == 200
        assert r.json()["username"] == self.username
        # 刷新轮换：旧 refresh 用一次后立即作废
        r = http_requests.post(f"{BASE_URL}/auth/refresh", json={"refresh_token": refresh}, timeout=10)
        assert r.status_code == 200
        new_tokens = r.json()
        assert new_tokens["refresh_token"] != refresh
        r = http_requests.post(f"{BASE_URL}/auth/refresh", json={"refresh_token": refresh}, timeout=10)
        assert r.status_code == 401  # 旧 refresh 复用被拒
        # 登出后 access 立即失效
        access2 = new_tokens["access_token"]
        r = http_requests.post(
            f"{BASE_URL}/auth/logout", timeout=10,
            headers={"Authorization": f"Bearer {access2}"},
            json={"refresh_token": new_tokens["refresh_token"]},
        )
        assert r.status_code == 200
        r = http_requests.get(f"{BASE_URL}/me", headers={"Authorization": f"Bearer {access2}"}, timeout=10)
        assert r.status_code == 401
        # 重新登录成功
        assert self._login().status_code == 200

    def test_login_lockout_after_failures(self):
        """连续失败 5 次触发 15 分钟锁定（429），正确密码也被拒"""
        self._register()
        for _ in range(5):
            r = self._login("wrongpass1")
            assert r.status_code == 401
        r = self._login(self.password)  # 正确密码也被锁定
        assert r.status_code == 429
