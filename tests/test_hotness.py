"""书籍热度评分与互动逻辑单元测试（不依赖数据库/Redis，用假对象隔离）。"""

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import hotness_service as hs
from app.services.hotness_service import HotnessService, compute_scores, decay_factor

NOW = datetime.now(timezone.utc)


# ---------- 假对象 ----------


class FakeBook:
    def __init__(self, id, title, author="Author", cover_url=None):
        self.id = id
        self.title = title
        self.author = author
        self.cover_url = cover_url


class FakeBookRepo:
    def __init__(self, books):
        self.books = {b.id: b for b in books}

    async def get_by_id(self, book_id):
        return self.books.get(book_id)

    async def list_by_ids(self, book_ids):
        return [self.books[i] for i in book_ids if i in self.books]


class FakeEventRepo:
    """假事件表：events = [(book_id, event_type, created_at)]"""

    def __init__(self, events=None):
        self.events = list(events or [])

    async def add(self, book_id, user_id, event_type):
        self.events.append((book_id, event_type, datetime.now(timezone.utc)))

    async def iter_events_since(self, since):
        return [(b, t, c) for b, t, c in self.events if c >= since]


class FakeInteractionRepo:
    """假互动表：rows[(book_id, user_id)] = {liked, liked_at, favorited, favorited_at}"""

    _DEFAULT = {"liked": False, "liked_at": None, "favorited": False, "favorited_at": None}

    def __init__(self, rows=None):
        self.rows = {(b, u): dict(d) for (b, u), d in (rows or {}).items()}

    def _row(self, book_id, user_id):
        return self.rows.setdefault((book_id, user_id), dict(self._DEFAULT))

    async def get(self, book_id, user_id):
        d = self.rows.get((book_id, user_id))
        return None if d is None else SimpleNamespace(**d)

    async def toggle(self, book_id, user_id, kind):
        field = "liked" if kind == "like" else "favorited"
        row = self._row(book_id, user_id)
        row[field] = not row[field]
        row[field + "_at"] = datetime.now(timezone.utc) if row[field] else None
        return row[field]

    async def count_active(self, book_id, kind):
        field = "liked" if kind == "like" else "favorited"
        return sum(1 for (b, _u), d in self.rows.items() if b == book_id and d[field])

    async def iter_active_since(self, since, kind):
        field, ts = ("liked", "liked_at") if kind == "like" else ("favorited", "favorited_at")
        return [(b, d[ts]) for (b, _u), d in self.rows.items() if d[field] and d[ts] >= since]


class FakeRedis:
    """覆盖热度功能用到的 Redis 子集；fail=True 时模拟 Redis 不可用"""

    def __init__(self, fail=False):
        self.fail = fail
        self.zsets: dict[str, dict] = {}
        self.hashes: dict[str, dict] = {}
        self.pfs: dict[str, set] = {}

    def _check(self):
        if self.fail:
            raise RuntimeError("redis down")

    async def pfadd(self, key, member):
        self._check()
        members = self.pfs.setdefault(key, set())
        if member in members:
            return 0
        members.add(member)
        return 1

    async def expire(self, key, ttl):
        self._check()

    async def exists(self, key):
        return key in self.zsets

    async def delete(self, *keys):
        for k in keys:
            self.zsets.pop(k, None)
            self.hashes.pop(k, None)

    async def zadd(self, key, mapping):
        self.zsets.setdefault(key, {}).update(mapping)

    @staticmethod
    def _sorted(zset):
        return sorted(zset.items(), key=lambda kv: (-kv[1], kv[0]))

    async def zrevrange(self, key, start, stop, withscores=False):
        items = self._sorted(self.zsets.get(key, {}))
        end = None if stop < 0 else stop + 1  # 与 Redis 一致：负数下标表示取到末尾
        out = items[start:end]
        return list(out) if withscores else [m for m, _s in out]

    async def zrevrank(self, key, member):
        order = [m for m, _s in self._sorted(self.zsets.get(key, {}))]
        return order.index(member) if member in order else None

    async def hgetall(self, key):
        return dict(self.hashes.get(key, {}))

    async def hset(self, key, mapping=None):
        self.hashes.setdefault(key, {}).update(mapping or {})


def make_service(events=None, interactions=None, books=None):
    return HotnessService(
        db=None,
        event_repo=FakeEventRepo(events),
        interaction_repo=FakeInteractionRepo(interactions),
        book_repo=FakeBookRepo(
            books or [FakeBook(1, "Book1"), FakeBook(2, "Book2")]
        ),
    )


def bind_fake_redis(monkeypatch, fake=None):
    fake = fake or FakeRedis()
    monkeypatch.setattr(hs, "get_redis", lambda: fake)
    return fake


# ---------- 衰减与评分（纯函数） ----------


def test_decay_factor_half_life():
    assert decay_factor(0) == 1.0
    assert decay_factor(14) == pytest.approx(0.5)
    assert decay_factor(28) == pytest.approx(0.25)


def test_compute_scores_empty():
    assert compute_scores({}) == {}


def test_compute_scores_single_book_full_score():
    assert compute_scores({1: {"view": 1.0}}) == {1: 100.0}


def test_compute_scores_recent_beats_older():
    scores = compute_scores({1: {"view": 10.0}, 2: {"view": 10.0 * decay_factor(14)}})
    assert scores[1] == 100.0
    assert 0.0 <= scores[2] < scores[1]


def test_compute_scores_favorite_beats_like():
    scores = compute_scores({1: {"favorite": 1.0}, 2: {"like": 1.0}})
    assert scores[1] == 100.0 and scores[2] == 0.0


def test_compute_scores_shrinks_small_samples():
    # 1 条收藏的小样本 vs 大量浏览的大样本：收缩后大样本胜出，避免单条高权重行为霸榜
    scores = compute_scores({1: {"favorite": 1.0}, 2: {"view": 100.0}})
    assert scores[2] > scores[1]


def test_compute_scores_tie_all_full_score():
    scores = compute_scores({1: {"view": 2.0}, 2: {"view": 2.0}})
    assert scores[1] == scores[2] == 100.0


# ---------- 聚合 ----------


def test_aggregate_applies_half_life_decay():
    svc = make_service(
        events=[
            (1, "view", NOW),
            (1, "view", NOW - timedelta(days=14)),
            (1, "view", NOW - timedelta(days=28)),
        ]
    )
    agg = asyncio.run(svc._aggregate())
    assert agg[1]["view"] == pytest.approx(1.0 + 0.5 + 0.25)


def test_aggregate_clamps_future_events():
    svc = make_service(events=[(1, "view", NOW + timedelta(hours=1))])
    agg = asyncio.run(svc._aggregate())
    assert agg[1]["view"] == pytest.approx(1.0)


def test_aggregate_includes_likes_and_favorites():
    svc = make_service(
        interactions={
            (1, 7): {
                "liked": True,
                "liked_at": NOW,
                "favorited": True,
                "favorited_at": NOW - timedelta(days=14),
            }
        }
    )
    agg = asyncio.run(svc._aggregate())
    assert agg[1]["like"] == pytest.approx(1.0)
    assert agg[1]["favorite"] == pytest.approx(0.5)


# ---------- 事件写入：日去重 ----------


def test_record_event_dedups_per_day(monkeypatch):
    svc = make_service()
    bind_fake_redis(monkeypatch)
    asyncio.run(svc.record_event(1, 7, "view"))
    asyncio.run(svc.record_event(1, 7, "view"))  # 同人同书同类型：去重
    asyncio.run(svc.record_event(1, 8, "view"))  # 不同用户：不去重
    assert len(svc.event_repo.events) == 2


def test_record_event_falls_back_when_redis_down(monkeypatch):
    svc = make_service()
    bind_fake_redis(monkeypatch, FakeRedis(fail=True))
    asyncio.run(svc.record_event(1, 7, "view"))
    assert len(svc.event_repo.events) == 1  # Redis 挂了也不丢事件


def test_record_event_rejects_unknown_book(monkeypatch):
    svc = make_service()
    bind_fake_redis(monkeypatch)
    with pytest.raises(HTTPException):
        asyncio.run(svc.record_event(999, 7, "view"))


# ---------- 点赞/收藏 toggle ----------


def test_toggle_like_twice_returns_to_initial(monkeypatch):
    svc = make_service()
    bind_fake_redis(monkeypatch)
    first = asyncio.run(svc.toggle_interaction(1, 7, "like"))
    assert first["liked"] is True and first["like_count"] == 1
    again = asyncio.run(svc.toggle_interaction(1, 7, "like"))
    assert again["liked"] is False and again["like_count"] == 0


def test_toggle_like_and_favorite_independent(monkeypatch):
    svc = make_service()
    bind_fake_redis(monkeypatch)
    asyncio.run(svc.toggle_interaction(1, 7, "like"))
    fav = asyncio.run(svc.toggle_interaction(1, 7, "favorite"))
    assert fav["favorited"] is True and fav["favorite_count"] == 1
    assert fav["liked"] is True and fav["like_count"] == 1


# ---------- 重算与榜单 ----------


def test_recompute_writes_ranking_and_detail(monkeypatch):
    svc = make_service(
        events=[(1, "view", NOW), (2, "view", NOW), (2, "view", NOW)],
        interactions={
            (1, 7): {"liked": True, "liked_at": NOW, "favorited": False, "favorited_at": None}
        },
    )
    fake = bind_fake_redis(monkeypatch)
    scores = asyncio.run(svc.recompute())
    assert set(scores) == {1, 2}

    raw = asyncio.run(fake.zrevrange("hot:ranking", 0, -1, withscores=True))
    assert {m for m, _s in raw} == {"1", "2"}
    detail2 = asyncio.run(fake.hgetall("hot:book:2"))
    assert detail2["views"] == 2 and detail2["likes"] == 0
    detail1 = asyncio.run(fake.hgetall("hot:book:1"))
    assert detail1["likes"] == 1


def test_get_ranking_orders_by_score_with_book_info(monkeypatch):
    svc = make_service(
        events=[(1, "view", NOW)],
        interactions={
            (2, 7): {"liked": True, "liked_at": NOW, "favorited": True, "favorited_at": NOW}
        },
    )
    bind_fake_redis(monkeypatch)
    ranking = asyncio.run(svc.get_ranking(limit=10))
    assert ranking[0]["rank"] == 1 and ranking[0]["book_id"] == 2
    assert ranking[1]["rank"] == 2 and ranking[1]["book_id"] == 1
    assert ranking[0]["title"] == "Book2"


def test_get_book_hotness_merges_state_and_rank(monkeypatch):
    svc = make_service(
        events=[(1, "view", NOW)],
        interactions={
            (1, 7): {"liked": True, "liked_at": NOW, "favorited": False, "favorited_at": None}
        },
    )
    bind_fake_redis(monkeypatch)
    detail = asyncio.run(svc.get_book_hotness(1, 7))
    assert detail["book_id"] == 1
    assert detail["rank"] == 1
    assert detail["breakdown"]["views"] == 1
    assert detail["liked"] is True and detail["like_count"] == 1
    assert detail["favorited"] is False


def test_get_book_hotness_zero_interaction_book(monkeypatch):
    svc = make_service(events=[(1, "view", NOW)])
    bind_fake_redis(monkeypatch)
    detail = asyncio.run(svc.get_book_hotness(2, 7))
    assert detail["score"] == 0.0
    assert detail["rank"] is None
    assert detail["breakdown"]["views"] == 0


def test_get_book_hotness_rejects_unknown_book(monkeypatch):
    svc = make_service()
    bind_fake_redis(monkeypatch)
    with pytest.raises(HTTPException):
        asyncio.run(svc.get_book_hotness(999, 7))
