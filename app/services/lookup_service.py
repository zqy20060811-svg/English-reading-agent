"""点词查义业务逻辑：LLM 查词 + Redis 缓存 + 每日配额。

- 缓存命中：直接返回释义，不消耗当日配额（同一单词全书用户只查一次模型）
- 缓存未命中：校验每日配额 → 调 LLM → 结果写入缓存 → 返回
"""

import json
import re
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.redis import get_redis
from app.db.database import get_db
from app.schemas.study import WordLookupResponse
from app.services.llm_service import LLMService
from app.services.quota_service import check_daily_quota
from app.services.usage_service import record_llm_usage

# 查词结果缓存 7 天（词典内容稳定，长缓存摊薄模型成本）
LOOKUP_CACHE_TTL_SECONDS = 7 * 24 * 3600

# 查词系统提示词：要求严格 JSON 输出，面向中文学习者的释义
LOOKUP_SYSTEM_PROMPT = (
    "You are an English dictionary assistant for Chinese learners.\n"
    "Given an English word, respond with ONLY a JSON object (no markdown fences, no extra text):\n"
    '{"word": "<the word>", "phonetic": "<IPA phonetic, empty if unsure>", '
    '"senses": ["<词性. 中文释义>", ...2-4 most common senses], '
    '"example_en": "<one simple English example sentence>", '
    '"example_cn": "<例句中文翻译>"}\n'
    "All values except the word itself must be in Chinese where natural."
)

# 合法单词字符：字母 + 连字符 + 撇号（允许 don't / well-known）
_WORD_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z'-]*$")


def normalize_lookup_word(word: str) -> str:
    """查词归一化与合法性校验：去空白转小写，仅允许英文单词形态"""
    w = word.strip().lower()
    if not w or len(w) > 64 or not _WORD_PATTERN.match(w):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"「{word}」不是有效的英文单词")
    return w


def _parse_lookup_json(raw: str, word: str) -> WordLookupResponse:
    """解析模型返回的 JSON（容错：剥掉 markdown 代码块围栏）"""
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        # 模型偶尔不守格式：降级为纯文本释义，保证功能可用
        return WordLookupResponse(word=word, senses=[raw.strip()[:200]])
    senses = [str(s).strip() for s in data.get("senses", []) if str(s).strip()]
    return WordLookupResponse(
        word=word,
        phonetic=str(data.get("phonetic", "")).strip(),
        senses=senses,
        example_en=str(data.get("example_en", "")).strip(),
        example_cn=str(data.get("example_cn", "")).strip(),
    )


def _deepseek_lookup(llm: LLMService, word: str) -> str:
    """DeepSeek 查词（同步阻塞，由调用方放入线程池）；token 用量记入 llm.usage_log"""
    payload = LLMService._build_payload(LOOKUP_SYSTEM_PROMPT, word)
    payload["temperature"] = 0.2
    return llm._request_chat(payload, "查词")


class LookupService:
    """点词查义服务"""

    def __init__(self, redis: Redis, db: AsyncSession):
        self.redis = redis
        self.db = db  # 用量落库用（旁路统计）

    async def lookup_cached_only(self, word: str) -> WordLookupResponse | None:
        """仅读缓存不调模型：生词本批量释义用，未命中/无效词返回 None"""
        w = word.strip().lower()
        if not w or len(w) > 64 or not _WORD_PATTERN.match(w):
            return None
        cached = await self.redis.get(f"lookup:word:{w}")
        if not cached:
            return None
        result = _parse_lookup_json(cached, w)
        result.cached = True
        return result

    async def lookup(self, user_id: int, word: str) -> WordLookupResponse:
        word = normalize_lookup_word(word)
        cache_key = f"lookup:word:{word}"

        # 1) 缓存命中直接返回
        cached = await self.redis.get(cache_key)
        if cached:
            result = _parse_lookup_json(cached, word)
            result.cached = True
            return result

        # 2) 未命中：先占配额再调模型（失败不缓存，避免污染）
        await check_daily_quota(user_id, "查词", get_settings().QUOTA_LOOKUP_DAILY, self.redis)
        llm = LLMService()
        raw = await run_in_threadpool(_deepseek_lookup, llm, word)
        result = _parse_lookup_json(raw, word)

        await self.redis.set(cache_key, raw, ex=LOOKUP_CACHE_TTL_SECONDS)
        # LLM token 用量落库（旁路：失败不影响查词主流程）
        await record_llm_usage(self.db, user_id, llm)
        return result


def get_lookup_service(
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> LookupService:
    """FastAPI 依赖注入：共享单例 Redis 客户端 + 请求级数据库会话"""
    return LookupService(redis, db)
