from redis.asyncio import Redis

from app.core.security import get_token_ttl_seconds

KEY_PREFIX = "token:"


class TokenRepository:
    """token 的 Redis 存取层：key 为 token:{token}，value 为 user_id"""

    def __init__(self, redis: Redis):
        self.redis = redis

    async def save(self, token: str, user_id: int) -> None:
        """登录后存储 token，TTL 与 JWT 过期时间一致"""
        await self.redis.set(KEY_PREFIX + token, user_id, ex=get_token_ttl_seconds())

    async def exists(self, token: str) -> bool:
        """校验 token 是否仍有效（未被登出）"""
        return await self.redis.exists(KEY_PREFIX + token) == 1

    async def delete(self, token: str) -> None:
        """登出时删除 token"""
        await self.redis.delete(KEY_PREFIX + token)
