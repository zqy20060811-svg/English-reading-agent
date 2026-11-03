"""LLM 用量持久化服务：把 LLMService.usage_log 流水写入 llm_usage_log 表。

记录失败不影响主业务流程（统计是旁路数据）。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.llm_usage import LLMUsageLog
from app.services.llm_service import LLMService


async def record_llm_usage(db: AsyncSession | None, user_id: int, llm: LLMService) -> None:
    """把本次请求实例累积的 token 用量流水落库（尽力而为，失败静默）"""
    if db is None or not llm.usage_log:
        return
    try:
        for entry in llm.usage_log:
            db.add(LLMUsageLog(
                user_id=user_id,
                scene=entry.get("scene") or "其他",
                model=entry.get("model") or "",
                prompt_tokens=entry.get("prompt_tokens") or 0,
                completion_tokens=entry.get("completion_tokens") or 0,
            ))
        await db.commit()
    except Exception:  # 统计旁路失败不影响主流程
        await db.rollback()


def estimate_cost_usd(prompt_tokens: int, completion_tokens: int) -> float:
    """按 DeepSeek 官方定价估算成本（美元）。

    deepseek-chat：输入 $0.27/百万 tokens，输出 $1.10/百万 tokens
    （2025-09 起价格，可在配置中覆盖）
    """
    s = get_settings()
    return round(
        prompt_tokens / 1e6 * s.LLM_INPUT_PRICE_PER_M
        + completion_tokens / 1e6 * s.LLM_OUTPUT_PRICE_PER_M,
        6,
    )
