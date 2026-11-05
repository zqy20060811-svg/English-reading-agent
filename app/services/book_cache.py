"""书库列表 Redis 缓存：版本号失效（INCR），旧版本 key 靠 TTL 自然过期。

书库列表对所有用户相同，是典型的读多写少数据；入库/上下架/同步等
写操作递增版本号使全部列表 key 立即失效，无需枚举删除。
"""

import json

from redis.asyncio import Redis

from app.schemas.book import BookOut

LIST_VER_KEY = "books:list:ver"
LIST_TTL_SECONDS = 600  # 列表缓存 10 分钟（兜底：写操作未失效时数据也不会太旧）


async def bump_books_cache(redis: Redis) -> None:
    """书库内容变化（入库/上下架/同步）后调用：递增版本号使列表缓存立即失效"""
    await redis.incr(LIST_VER_KEY)


async def get_cached_books(redis: Redis, limit: int, fetch) -> list:
    """带缓存的书籍列表获取：命中返回缓存 JSON，未命中调用 fetch() 并写回。

    Redis 异常时自动降级直查数据库，不影响书库可用性。
    """
    payload = None
    try:
        ver = await redis.get(LIST_VER_KEY)
        raw = await redis.get(f"books:list:v{ver or 0}:{limit}")
        if raw:
            payload = json.loads(raw)
    except Exception:
        payload = None  # Redis 不可用/数据损坏 → 降级直查
    if payload is not None:
        return payload

    books = await fetch()
    payload = [BookOut.model_validate(b).model_dump(mode="json") for b in books]
    try:
        await redis.set(
            f"books:list:v{await redis.get(LIST_VER_KEY) or 0}:{limit}",
            json.dumps(payload, ensure_ascii=False),
            ex=LIST_TTL_SECONDS,
        )
    except Exception:
        pass  # 写缓存失败不影响本次响应
    return payload
