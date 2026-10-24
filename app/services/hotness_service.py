import math
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.redis import get_redis
from app.db.database import AsyncSessionLocal, get_db
from app.repositories.book_event_repository import BookEventRepository
from app.repositories.book_interaction_repository import BookInteractionRepository
from app.repositories.book_repository import BookRepository

# 行为权重：收藏 > 点赞 > 读完章节 > 浏览（越主动的行为权重越高）
EVENT_WEIGHTS = {"view": 1.0, "finish_chapter": 3.0, "like": 4.0, "favorite": 5.0}
HALF_LIFE_DAYS = 14.0  # 指数半衰期：每过 14 天行为权重减半
BAYES_PRIOR_STRENGTH = 5.0  # 贝叶斯收缩先验强度：等效 5 个单位活跃度的先验
CACHE_TTL_SECONDS = 600  # 热度缓存有效期：10 分钟，过期后惰性重算
RANKING_KEY = "hot:ranking"  # ZSET：member=book_id, score=0-100
BOOK_KEY_PREFIX = "hot:book:"  # HASH：单本书总分与分项明细
_VIEW_DEDUP_TTL_SECONDS = 172800  # 浏览去重键保留两天，覆盖跨天边界
_BREAKDOWN_FIELDS = ("views", "finish_chapters", "likes", "favorites")


def decay_factor(age_days: float) -> float:
    """指数半衰期衰减：age = HALF_LIFE_DAYS 时权重衰减到 0.5"""
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def compute_scores(per_book: dict[int, dict[str, float]]) -> dict[int, float]:
    """热度分计算（纯函数，便于单测）。

    输入：{book_id: {事件类型: 窗口内衰减和}}，衰减和 = Σ decay_factor(行为距今天数)
    步骤：按行为加权求和 -> log1p 压缩 -> 贝叶斯收缩 -> min-max 归一化到 0-100。
    书籍属长尾低互动内容，HN 式平方压制会抹平差异，故用温和的 log 压缩；
    贝叶斯收缩避免"少量用户集中刷一条高权重行为"的小样本书籍霸榜。
    """
    if not per_book:
        return {}

    compressed: dict[int, float] = {}
    activity: dict[int, float] = {}
    for book_id, per_type in per_book.items():
        weighted = sum(EVENT_WEIGHTS.get(t, 0.0) * v for t, v in per_type.items())
        compressed[book_id] = math.log1p(weighted)
        activity[book_id] = sum(per_type.values())

    # 贝叶斯收缩：小样本书籍的分数向全局均值收缩
    prior = sum(compressed.values()) / len(compressed)
    shrunk = {
        book_id: (activity[book_id] / (activity[book_id] + BAYES_PRIOR_STRENGTH)) * score
        + (BAYES_PRIOR_STRENGTH / (activity[book_id] + BAYES_PRIOR_STRENGTH)) * prior
        for book_id, score in compressed.items()
    }

    lo, hi = min(shrunk.values()), max(shrunk.values())
    if hi - lo < 1e-9:
        # 全部持平：有互动的书籍并列满分
        return {book_id: 100.0 for book_id in shrunk}
    return {
        book_id: round((score - lo) / (hi - lo) * 100, 2)
        for book_id, score in shrunk.items()
    }


def _ensure_utc(dt: datetime) -> datetime:
    """兼容 SQLite 等返回 naive datetime 的场景"""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d")


class HotnessService:
    """书籍热度：加权行为 + 14 天指数半衰期 + 贝叶斯收缩 + Redis 缓存榜单"""

    def __init__(
        self,
        db: AsyncSession,
        event_repo: BookEventRepository | None = None,
        interaction_repo: BookInteractionRepository | None = None,
        book_repo: BookRepository | None = None,
    ):
        self.db = db
        self.event_repo = event_repo or BookEventRepository(db)
        self.interaction_repo = interaction_repo or BookInteractionRepository(db)
        self.book_repo = book_repo or BookRepository(db)

    # ---------- 行为写入 ----------

    async def record_event(self, book_id: int, user_id: int, event_type: str) -> None:
        """记录浏览/读完章节事件：Redis 日去重（同人同书同类型每天最多计 1 次）"""
        book = await self.book_repo.get_by_id(book_id)
        if book is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"书籍 {book_id} 不存在")

        redis = get_redis()
        dedup_key = f"hot:seen:{_today()}:{event_type}:{book_id}"
        try:
            is_new = await redis.pfadd(dedup_key, str(user_id))
            await redis.expire(dedup_key, _VIEW_DEDUP_TTL_SECONDS)
        except Exception:
            is_new = True  # Redis 不可用时退化为不去重，保证事件不丢
        if is_new:
            await self.event_repo.add(book_id, user_id, event_type)

    async def toggle_interaction(self, book_id: int, user_id: int, kind: str) -> dict:
        """切换点赞/收藏状态，返回最新状态与计数"""
        book = await self.book_repo.get_by_id(book_id)
        if book is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"书籍 {book_id} 不存在")
        await self.interaction_repo.toggle(book_id, user_id, kind)
        return await self.interaction_state(book_id, user_id)

    async def interaction_state(self, book_id: int, user_id: int) -> dict:
        """当前用户对某本书的互动状态 + 全局计数"""
        row = await self.interaction_repo.get(book_id, user_id)
        return {
            "liked": bool(row and row.liked),
            "favorited": bool(row and row.favorited),
            "like_count": await self.interaction_repo.count_active(book_id, "like"),
            "favorite_count": await self.interaction_repo.count_active(book_id, "favorite"),
        }

    # ---------- 评分与缓存 ----------

    async def _aggregate(self) -> dict[int, dict[str, float]]:
        """窗口内行为聚合为 {book_id: {事件类型: 衰减和}}"""
        now = datetime.now(timezone.utc)
        since = now - timedelta(days=BookEventRepository.WINDOW_DAYS)
        per_book: dict[int, dict[str, float]] = {}

        for book_id, event_type, created_at in await self.event_repo.iter_events_since(since):
            age_days = max((now - _ensure_utc(created_at)).total_seconds() / 86400, 0.0)
            per_book.setdefault(book_id, {}).setdefault(event_type, 0.0)
            per_book[book_id][event_type] += decay_factor(age_days)

        for kind in ("like", "favorite"):
            for book_id, active_at in await self.interaction_repo.iter_active_since(since, kind):
                age_days = max((now - _ensure_utc(active_at)).total_seconds() / 86400, 0.0)
                per_book.setdefault(book_id, {}).setdefault(kind, 0.0)
                per_book[book_id][kind] += decay_factor(age_days)
        return per_book

    async def recompute(self) -> dict[int, float]:
        """全量重算热度并写入 Redis（榜单 ZSET + 单书 HASH），缓存 miss 时惰性触发"""
        per_book = await self._aggregate()
        scores = compute_scores(per_book)

        # 分项明细：窗口内行为计数（非衰减值，仅展示用）
        since = datetime.now(timezone.utc) - timedelta(days=BookEventRepository.WINDOW_DAYS)
        breakdowns: dict[int, dict[str, int]] = {}
        for book_id, event_type, _created_at in await self.event_repo.iter_events_since(since):
            row = breakdowns.setdefault(book_id, dict.fromkeys(_BREAKDOWN_FIELDS, 0))
            if event_type == "view":
                row["views"] += 1
            elif event_type == "finish_chapter":
                row["finish_chapters"] += 1
        for kind, field in (("like", "likes"), ("favorite", "favorites")):
            for book_id, _active_at in await self.interaction_repo.iter_active_since(since, kind):
                breakdowns.setdefault(book_id, dict.fromkeys(_BREAKDOWN_FIELDS, 0))[field] += 1

        redis = get_redis()
        await redis.delete(RANKING_KEY)
        if scores:
            await redis.zadd(RANKING_KEY, {str(bid): s for bid, s in scores.items()})
        await redis.expire(RANKING_KEY, CACHE_TTL_SECONDS)
        for book_id, score in scores.items():
            key = f"{BOOK_KEY_PREFIX}{book_id}"
            detail = breakdowns.get(book_id, dict.fromkeys(_BREAKDOWN_FIELDS, 0))
            mapping = {"score": score, **{k: int(detail[k]) for k in _BREAKDOWN_FIELDS}}
            await redis.hset(key, mapping=mapping)
            await redis.expire(key, CACHE_TTL_SECONDS)
        return scores

    async def get_ranking(self, limit: int = 20) -> list[dict]:
        """热门榜单：优先读缓存，缓存失效时惰性全量重算"""
        redis = get_redis()
        if not await redis.exists(RANKING_KEY):
            await self.recompute()
        raw = await redis.zrevrange(RANKING_KEY, 0, limit - 1, withscores=True)
        if not raw:
            return []

        book_ids = [int(member) for member, _score in raw]
        books = {b.id: b for b in await self.book_repo.list_by_ids(book_ids)}
        ranking = []
        for rank, (member, score) in enumerate(raw, start=1):
            book = books.get(int(member))
            if book is None:  # 缓存中残留已下架书籍时跳过
                continue
            ranking.append(
                {
                    "rank": rank,
                    "book_id": book.id,
                    "title": book.title,
                    "author": book.author,
                    "cover_url": book.cover_url,
                    "score": round(float(score), 2),
                }
            )
        return ranking

    async def get_book_hotness(self, book_id: int, user_id: int) -> dict:
        """单本书热度详情（合并当前用户互动状态）；无任何行为的书籍返回 0 分"""
        book = await self.book_repo.get_by_id(book_id)
        if book is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"书籍 {book_id} 不存在")

        redis = get_redis()
        key = f"{BOOK_KEY_PREFIX}{book_id}"
        cached = await redis.hgetall(key)
        if not cached:
            await self.recompute()
            cached = await redis.hgetall(key)

        score = float(cached.get("score", 0.0))
        breakdown = {field: int(cached.get(field, 0)) for field in _BREAKDOWN_FIELDS}
        raw_rank = await redis.zrevrank(RANKING_KEY, str(book_id))
        state = await self.interaction_state(book_id, user_id)
        return {
            "book_id": book_id,
            "score": score,
            "rank": raw_rank + 1 if raw_rank is not None else None,
            "breakdown": breakdown,
            **state,
        }


async def record_view_in_background(book_id: int, user_id: int) -> None:
    """后台任务记录浏览事件：独立数据库会话，任何失败静默，不影响阅读主流程"""
    try:
        async with AsyncSessionLocal() as session:
            await HotnessService(session).record_event(book_id, user_id, "view")
    except Exception:  # noqa: BLE001 热度统计失败不应影响阅读
        pass


def get_hotness_service(db: AsyncSession = Depends(get_db)) -> HotnessService:
    return HotnessService(db)
