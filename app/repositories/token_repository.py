from redis.asyncio import Redis

from app.core.security import get_access_ttl_seconds, get_refresh_ttl_seconds

ACCESS_KEY_PREFIX = "token:"  # token:{access_token} -> user_id
REFRESH_KEY_PREFIX = "auth:refresh:"  # auth:refresh:{refresh_token} -> user_id
# 反向索引：user_tokens:{uid} / user_refresh_tokens:{uid} 记录某用户的全部 token，
# 用于改密/登出时一键吊销（成员过期后为惰性残留，吊销时按需清理即可）
USER_ACCESS_SET_PREFIX = "user_tokens:"
USER_REFRESH_SET_PREFIX = "user_refresh_tokens:"


class TokenRepository:
    """token 的 Redis 存取层：access JWT 与不透明 refresh token 双轨存储"""

    def __init__(self, redis: Redis):
        self.redis = redis

    # ---------- Access Token ----------

    async def save(self, token: str, user_id: int) -> None:
        """登录后存储 access token，TTL 与 JWT 过期时间一致，并写入用户反向索引"""
        await self.redis.set(ACCESS_KEY_PREFIX + token, user_id, ex=get_access_ttl_seconds())
        await self.redis.sadd(USER_ACCESS_SET_PREFIX + str(user_id), token)

    async def exists(self, token: str) -> bool:
        """校验 access token 是否仍有效（未被登出/吊销）"""
        return await self.redis.exists(ACCESS_KEY_PREFIX + token) == 1

    async def delete(self, token: str) -> None:
        """登出时删除单个 access token"""
        await self.redis.delete(ACCESS_KEY_PREFIX + token)

    async def revoke_all_for_user(self, user_id: int) -> None:
        """吊销某用户全部 access token（改密时调用），并清理反向索引"""
        set_key = USER_ACCESS_SET_PREFIX + str(user_id)
        tokens = await self.redis.smembers(set_key)
        if tokens:
            await self.redis.delete(*(ACCESS_KEY_PREFIX + t for t in tokens))
        await self.redis.delete(set_key)

    # ---------- Refresh Token ----------

    async def save_refresh(self, token: str, user_id: int) -> None:
        """存储 refresh token（TTL 7 天），并写入用户反向索引"""
        await self.redis.set(REFRESH_KEY_PREFIX + token, user_id, ex=get_refresh_ttl_seconds())
        await self.redis.sadd(USER_REFRESH_SET_PREFIX + str(user_id), token)

    async def get_refresh_user_id(self, token: str) -> int | None:
        """校验 refresh token 并返回 user_id；无效返回 None"""
        value = await self.redis.get(REFRESH_KEY_PREFIX + token)
        return int(value) if value is not None else None

    async def delete_refresh(self, token: str) -> None:
        """删除单个 refresh token（登出或轮换时调用）"""
        await self.redis.delete(REFRESH_KEY_PREFIX + token)

    async def revoke_all_refresh_for_user(self, user_id: int) -> None:
        """吊销某用户全部 refresh token（改密时调用），并清理反向索引"""
        set_key = USER_REFRESH_SET_PREFIX + str(user_id)
        tokens = await self.redis.smembers(set_key)
        if tokens:
            await self.redis.delete(*(REFRESH_KEY_PREFIX + t for t in tokens))
        await self.redis.delete(set_key)
