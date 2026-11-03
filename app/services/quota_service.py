"""每日配额服务：按用户 + 场景做 Redis 计数限流（如翻译/问答每日次数）"""

from datetime import date

from redis.asyncio import Redis


class QuotaExceededError(Exception):
    """超出每日配额"""


async def check_daily_quota(user_id: int, scene: str, limit: int, redis: Redis) -> int:
    """校验并累加当日用量，超限抛 QuotaExceededError；返回已用次数"""
    key = f"quota:{scene}:{user_id}:{date.today().isoformat()}"
    count = await redis.incr(key)
    if count == 1:
        # 首次写入设置 48 小时过期（跨日安全冗余，自然淘汰历史 key）
        await redis.expire(key, 172800)
    if count > limit:
        raise QuotaExceededError(f"今日{scene}次数已达上限（{limit} 次），请明日再试")
    return count
