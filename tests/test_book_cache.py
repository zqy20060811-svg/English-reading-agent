"""书库列表 Redis 缓存单元测试（假 Redis，不依赖数据库）。"""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.services.book_cache import bump_books_cache, get_cached_books


class FakeRedis:
    """覆盖列表缓存用到的 Redis 子集；fail=True 时模拟 Redis 不可用"""

    def __init__(self, fail=False):
        self.fail = fail
        self.strings: dict[str, str] = {}

    async def get(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        return self.strings.get(key)

    async def set(self, key, value, ex=None):
        if self.fail:
            raise ConnectionError("redis down")
        self.strings[key] = value

    async def incr(self, key):
        if self.fail:
            raise ConnectionError("redis down")
        val = int(self.strings.get(key) or 0) + 1
        self.strings[key] = str(val)
        return val


def make_book(i=1):
    return SimpleNamespace(
        id=i,
        gutenberg_id=100 + i,
        title=f"Book {i}",
        author="Author",
        year=1900,
        genre="Fiction",
        synopsis="...",
        cover_url="https://covers.openlibrary.org/b/id/1-L.jpg",
        language="en",
        source_url="https://gutenberg.org/ebooks/100",
        word_count=1000,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )


def test_cache_miss_fetches_and_writes():
    redis = FakeRedis()
    calls = []

    async def fetch():
        calls.append(1)
        return [make_book()]

    out = asyncio.run(get_cached_books(redis, 200, fetch))
    assert len(out) == 1 and out[0]["title"] == "Book 1"
    assert len(calls) == 1
    assert "books:list:v0:200" in redis.strings  # 结果已写入缓存


def test_cache_hit_skips_fetch():
    redis = FakeRedis()
    calls = []

    async def fetch():
        calls.append(1)
        return [make_book()]

    async def run():
        await get_cached_books(redis, 200, fetch)
        return await get_cached_books(redis, 200, fetch)

    out2 = asyncio.run(run())
    assert len(calls) == 1  # 第二次直接命中缓存
    assert out2[0]["id"] == 1


def test_bump_invalidates_cache():
    redis = FakeRedis()
    calls = []

    async def fetch():
        calls.append(1)
        return [make_book()]

    async def run():
        await get_cached_books(redis, 200, fetch)
        await bump_books_cache(redis)  # 版本号 0 → 1，旧 key 立即失效
        await get_cached_books(redis, 200, fetch)

    asyncio.run(run())
    assert len(calls) == 2  # 失效后重新查询并写入新版本 key
    assert "books:list:v1:200" in redis.strings


def test_redis_failure_falls_back_to_db():
    """Redis 不可用时降级直查数据库，不影响书库可用性"""
    redis = FakeRedis(fail=True)
    calls = []

    async def fetch():
        calls.append(1)
        return [make_book()]

    out = asyncio.run(get_cached_books(redis, 200, fetch))
    assert len(out) == 1 and len(calls) == 1  # 正常返回，未抛异常
