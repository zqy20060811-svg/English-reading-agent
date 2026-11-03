"""阶段4后台管理测试。

- TestCostEstimate：成本估算纯单元（始终运行）
- TestAdminDB：下架书籍可见性（需要本地 PostgreSQL，缺失自动跳过）
- TestIngestReliability：入库任务可靠性——启动恢复/原子领取/重复防护（需要 PostgreSQL）
- TestAdminHTTP：管理员权限 / 用户禁用 / 上下架 / 任务接口（需要后端运行中，不可达自动跳过）

运行：python -m pytest tests/test_admin.py -v
"""

import asyncio
import uuid

import pytest
import requests as http_requests
from fastapi import HTTPException
from sqlalchemy import select, update

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


# ================= 入库任务可靠性（P0：启动恢复 / 原子领取 / 重复防护） =================


@requires_db
class TestIngestReliability:
    """覆盖：重启卡死恢复、重复提交防护、原子领取、同书并发重试防护。

    注意：测试直接操作本地开发库，使用 9xxxxxx 段无效书号（crawl_one 对不在
    目录的书号立即抛 ValueError，不产生网络请求，后台任务毫秒级快速失败）。
    """

    @staticmethod
    async def _any_user_id() -> int:
        from app.db.database import AsyncSessionLocal
        from app.models.user import User

        async with AsyncSessionLocal() as db:
            return (await db.execute(select(User.id).limit(1))).scalar_one()

    @staticmethod
    async def _cleanup_tasks(*task_ids: int) -> None:
        from app.db.database import AsyncSessionLocal
        from app.models.ingest_task import IngestTask

        async with AsyncSessionLocal() as db:
            for tid in task_ids:
                t = await db.get(IngestTask, tid)
                if t:
                    await db.delete(t)
            await db.commit()

    @staticmethod
    async def _wait_status(task_id: int, status: str, timeout: float = 5.0) -> None:
        """轮询等待后台任务到达指定状态（无效书号快速失败，通常毫秒级）"""
        from app.db.database import AsyncSessionLocal
        from app.models.ingest_task import IngestTask

        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            async with AsyncSessionLocal() as db:
                t = await db.get(IngestTask, task_id)
                if t and t.status == status:
                    return
            await asyncio.sleep(0.1)
        raise AssertionError(f"任务 {task_id} 未在 {timeout}s 内到达状态 {status}")

    def test_startup_recovery_marks_running_failed(self):
        """场景1-3 验收：重启恢复把卡死的 running 标记为 failed（可重试），pending 重新调度"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.ingest_task import IngestTask
            from app.services.ingest_service import recover_interrupted_tasks

            uid = await self._any_user_id()
            gid = 910000 + int(uuid.uuid4().hex[:4], 16) % 80000
            async with AsyncSessionLocal() as db:
                stuck = IngestTask(gutenberg_id=gid, embed=False, status="running",
                                   attempts=1, created_by=uid)
                waiting = IngestTask(gutenberg_id=gid + 1, embed=False, status="pending",
                                     created_by=uid)
                db.add_all([stuck, waiting])
                await db.commit()
                stuck_id, waiting_id = stuck.id, waiting.id
            try:
                pending_ids = await recover_interrupted_tasks()
                async with AsyncSessionLocal() as db:
                    s = await db.get(IngestTask, stuck_id)
                    assert s.status == "failed"
                    assert "中断" in s.error and s.finished_at is not None
                    w = await db.get(IngestTask, waiting_id)
                    assert w.status == "pending"  # 尚未开始的任务保持待执行
                assert waiting_id in pending_ids  # 并纳入重新调度清单
            finally:
                await self._cleanup_tasks(stuck_id, waiting_id)

        _run(main())

    def test_duplicate_active_task_rejected(self):
        """场景4 验收：同书进行中任务存在时拒绝重复提交；失败后可再次提交"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.services.ingest_service import IngestService

            uid = await self._any_user_id()
            svc = IngestService(AsyncSessionLocal())
            t1 = await svc.create_task(999999996, embed=False, created_by=uid)
            try:
                with pytest.raises(HTTPException) as e:
                    await svc.create_task(999999996, embed=False, created_by=uid)
                assert e.value.status_code == 400 and "进行中" in e.value.detail
            finally:
                await self._cleanup_tasks(t1.id)
            # 首个任务已清理（等同失败终态），同书可再次提交
            t2 = await svc.create_task(999999996, embed=False, created_by=uid)
            try:
                assert t2.status == "pending"
            finally:
                await self._cleanup_tasks(t2.id)

        _run(main())

    def test_create_task_rejects_book_already_in_library(self):
        """书已在书库时拒绝重复入库（已成功任务不会因重复提交而重复入库）"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.book import Book
            from app.services.ingest_service import IngestService

            uid = await self._any_user_id()
            async with AsyncSessionLocal() as db:
                gid = (await db.execute(select(Book.gutenberg_id).limit(1))).scalar_one()
            svc = IngestService(AsyncSessionLocal())
            with pytest.raises(HTTPException) as e:
                await svc.create_task(gid, embed=False, created_by=uid)
            assert e.value.status_code == 400 and "已在书库" in e.value.detail

        _run(main())

    def test_atomic_claim_prevents_double_execution(self):
        """原子领取：非 pending 任务领取空转；重复调度不会重复执行（attempts 只加一次）"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.ingest_task import IngestTask
            from app.services import ingest_service as isvc

            uid = await self._any_user_id()
            async with AsyncSessionLocal() as db:
                t = IngestTask(gutenberg_id=999999995, embed=False, status="running",
                               attempts=1, created_by=uid)
                db.add(t)
                await db.commit()
                await db.refresh(t)
                tid = t.id
            try:
                # 非 pending：领取空转，状态与 attempts 不变
                await isvc._run(tid)
                async with AsyncSessionLocal() as db:
                    t = await db.get(IngestTask, tid)
                    assert t.status == "running" and t.attempts == 1

                # pending：领取后执行（无效书号快速失败），重复调度不重复执行
                async with AsyncSessionLocal() as db:
                    t = await db.get(IngestTask, tid)
                    t.status = "pending"
                    await db.commit()
                await isvc._run(tid)
                await isvc._run(tid)  # 第二次调度领取不到，直接返回
                await self._wait_status(tid, "failed")
                async with AsyncSessionLocal() as db:
                    t = await db.get(IngestTask, tid)
                    assert t.attempts == 2  # 初始 1 + 领取执行 1（不是 3）
            finally:
                await self._cleanup_tasks(tid)

        _run(main())

    def test_retry_blocked_while_another_task_active(self):
        """同书另有进行中任务时禁止重试；对方结束（failed）后可正常重试"""
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.ingest_task import IngestTask
            from app.services.ingest_service import IngestService

            uid = await self._any_user_id()
            gid = 999999994
            async with AsyncSessionLocal() as db:
                a = IngestTask(gutenberg_id=gid, embed=False, status="pending", created_by=uid)
                b = IngestTask(gutenberg_id=gid, embed=False, status="failed",
                               error="x", attempts=1, created_by=uid)
                db.add_all([a, b])
                await db.commit()
                a_id, b_id = a.id, b.id
            try:
                svc = IngestService(AsyncSessionLocal())
                with pytest.raises(HTTPException) as e:
                    await svc.retry_task(b_id)
                assert e.value.status_code == 400 and "进行中的任务" in e.value.detail

                # A 结束后 B 可重试（重试会调度后台执行，无效书号快速失败）
                async with AsyncSessionLocal() as db:
                    await db.execute(
                        update(IngestTask).where(IngestTask.id == a_id).values(status="failed")
                    )
                    await db.commit()
                retried = await svc.retry_task(b_id)
                assert retried.status == "pending"
                await self._wait_status(b_id, "failed")
            finally:
                await self._cleanup_tasks(a_id, b_id)

        _run(main())


# ================= 入库幂等性（run_ingest 重复执行 / 章节收缩 / 孤儿向量清理） =================


@requires_db
class TestIngestIdempotency:
    """run_ingest 幂等性与数据库写入策略验收：

    - 章节收缩时被删章节的分块（含向量）级联清理，不留孤儿向量
    - chunk_books 兜底清理历史孤儿分块
    - 分块重建后旧向量不残留（embedding 重置为 NULL，等待补算）
    """

    @staticmethod
    def _book_body() -> str:
        # 12 行 × 约 30 词 ≈ 360 词（> MIN_WORDS=150 防止过小章节被并入前章），
        # 且章标题间隔 > WIN_GAP=8 行防止窗口去重误吞
        return "\n".join(["the quick brown fox jumps over the lazy dog again " * 4] * 12)

    @staticmethod
    async def _cleanup_book(book_id: int) -> None:
        from app.db.database import AsyncSessionLocal
        from app.models.book import Book
        from app.models.book_chapter import BookChapter
        from app.models.book_chunk import BookChunk

        async with AsyncSessionLocal() as db:
            await db.execute(
                BookChunk.__table__.delete().where(BookChunk.book_id == book_id)
            )
            await db.execute(
                BookChapter.__table__.delete().where(BookChapter.book_id == book_id)
            )
            b = await db.get(Book, book_id)
            if b:
                await db.delete(b)
            await db.commit()

    def test_shrinking_chapters_cascade_deletes_chunks(self):
        """原文更新导致章节数减少：被删章节的分块与向量必须级联删除，不留孤儿"""
        import json as json_mod
        import tempfile
        from pathlib import Path

        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.book import Book
            from app.models.book_chapter import BookChapter
            from app.models.book_chunk import BookChunk
            from app.pipeline import chunk_books
            from app.services.chapter_service import sync_chapters_from_local

            suffix = uuid.uuid4().hex[:8]
            gid = 920000 + int(suffix[:4], 16) % 70000
            body = self._book_body()
            # 新版原文只有 2 章（旧库中该书有 3 章，模拟章节收缩）
            new_content = f"CHAPTER I.\n\n{body}\n\nCHAPTER II.\n\n{body}"

            async with AsyncSessionLocal() as db:
                book = Book(
                    gutenberg_id=gid, title=f"IdemTest {suffix}", author="tester",
                    year=2000, genre="test", synopsis="", language="en",
                    source_url="http://test", word_count=1000,
                )
                db.add(book)
                await db.commit()
                await db.refresh(book)
                book_id = book.id
                chapters = []
                for i in range(1, 4):
                    ch = BookChapter(
                        book_id=book_id, chapter_index=i, title=f"Old {i}",
                        content=f"old chapter {i} text " * 200, word_count=600,
                    )
                    db.add(ch)
                    chapters.append(ch)
                await db.commit()
                for ch in chapters:
                    await db.refresh(ch)
                    db.add(BookChunk(
                        book_id=book_id, chapter_id=ch.id, chunk_index=0,
                        chunk_text=f"old chunk {ch.chapter_index}",
                        embedding=[0.1] * 1024,  # 模拟已有向量
                    ))
                await db.commit()
            try:
                with tempfile.TemporaryDirectory() as tmp:
                    book_dir = Path(tmp) / f"book{gid}"
                    book_dir.mkdir()
                    (book_dir / "info.json").write_text(
                        json_mod.dumps({"gutenberg_id": gid, "title": f"IdemTest {suffix}"}),
                        encoding="utf-8",
                    )
                    (book_dir / "content.txt").write_text(new_content, encoding="utf-8")
                    stats = await sync_chapters_from_local(books_dir=Path(tmp), only_ids={gid})
                assert stats["chapters"] == 2  # 重新切分为 2 章

                await chunk_books([gid])  # 流水线第 3 步：重建分块

                async with AsyncSessionLocal() as db:
                    chs = (await db.execute(
                        select(BookChapter).where(BookChapter.book_id == book_id)
                    )).scalars().all()
                    assert {c.chapter_index for c in chs} == {1, 2}  # 第 3 章已删
                    chunks = (await db.execute(
                        select(BookChunk).where(BookChunk.book_id == book_id)
                    )).scalars().all()
                    live_ids = {c.id for c in chs}
                    # 无孤儿分块：所有 chunk 都挂在现存章节上
                    assert all(c.chapter_id in live_ids for c in chunks)
                    # 旧向量不残留：重建后的分块等待向量化（embedding 全为 NULL）
                    assert all(c.embedding is None for c in chunks)
                    assert len(chunks) >= 2
            finally:
                await self._cleanup_book(book_id)

        _run(main())

    def test_chunk_fk_guard_and_orphan_sweep(self):
        """FK 防线验证 + 兜底清扫：

        - book_chunks.chapter_id 外键（无级联）阻止「删章节留孤儿分块」——
          数据库层面保证不产生孤儿向量（这也是历史上章节收缩路径会 FK 报错的根因，
          现已由 sync_chapters 级联清理分块修复）
        - chunk_books 的孤儿清扫语句对正常数据无副作用
        """
        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.book import Book
            from app.models.book_chapter import BookChapter
            from app.models.book_chunk import BookChunk
            from app.pipeline import chunk_books

            suffix = uuid.uuid4().hex[:8]
            gid = 920000 + int(suffix[:4], 16) % 70000
            async with AsyncSessionLocal() as db:
                book = Book(
                    gutenberg_id=gid, title=f"OrphanTest {suffix}", author="tester",
                    year=2000, genre="test", synopsis="", language="en",
                    source_url="http://test", word_count=1000,
                )
                db.add(book)
                await db.commit()
                await db.refresh(book)
                book_id = book.id
                ch1 = BookChapter(
                    book_id=book_id, chapter_index=1, title="C1",
                    content="chapter one " * 200, word_count=400,
                )
                db.add(ch1)
                await db.commit()
                await db.refresh(ch1)
                db.add(BookChunk(
                    book_id=book_id, chapter_id=ch1.id, chunk_index=0,
                    chunk_text="c1 chunk", embedding=[0.2] * 1024,
                ))
                await db.commit()

                # 外键防线：章节仍有分块时直接删除章节必须被数据库拒绝
                with pytest.raises(Exception, match="book_chunks_chapter_id_fkey"):
                    await db.delete(ch1)
                    await db.commit()
                await db.rollback()

            try:
                # 兜底清扫对正常数据无副作用：合法章节与其分块保持原样
                await chunk_books([gid])
                async with AsyncSessionLocal() as db:
                    remain = (await db.execute(
                        select(BookChunk).where(BookChunk.book_id == book_id)
                    )).scalars().all()
                    assert remain  # 正文被重建为多个分块
                    chs = (await db.execute(
                        select(BookChapter).where(BookChapter.book_id == book_id)
                    )).scalars().all()
                    assert {c.chapter_index for c in chs} == {1}
                    live_ids = {c.id for c in chs}
                    # 全部挂在现存章节上，且重建后向量等待补算
                    assert all(c.chapter_id in live_ids for c in remain)
                    assert all(c.embedding is None for c in remain)
            finally:
                await self._cleanup_book(book_id)

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

    def test_create_task_rejects_existing_book(self):
        """任务创建：书已在书库时 HTTP 400 拒绝（不产生任务行，不重复入库）"""
        token, uid, _ = _register_and_login()
        _promote_admin(uid)
        h = {"Authorization": f"Bearer {token}"}
        gid = http_requests.get(f"{BASE}/admin/books?page=1", headers=h, timeout=10).json()[0][
            "gutenberg_id"
        ]
        r = http_requests.post(
            f"{BASE}/admin/ingest/tasks", headers=h, json={"gutenberg_id": gid, "embed": False},
            timeout=10,
        )
        assert r.status_code == 400
        assert "已在书库" in r.json()["detail"]


async def _undisable(user_id: int) -> None:
    from app.db.database import AsyncSessionLocal
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        user.is_disabled = False
        await db.commit()
