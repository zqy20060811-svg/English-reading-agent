from redis.asyncio import Redis

from app.core.config import get_settings

_client: Redis | None = None


def get_redis() -> Redis:
    """模块级单例 Redis 客户端（URL 中含数据库编号，如 /2）"""
    global _client
    if _client is None:
        _client = Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
    return _client
