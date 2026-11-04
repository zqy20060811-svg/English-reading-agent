"""个人书籍分析 LLM 调用层：复用 DeepSeek 封装，返回严格校验后的 JSON。

原则：
- LLM 只做本地统计无法完成的部分：章节难度结论、代表性复杂句难点、章节摘要
- 输出必须是结构化 JSON，校验失败自动重试一次，仍失败抛出异常（绝不污染数据库）
- 每次调用记录 scene / model / token / 耗时，由调用方写入 llm_usage_log
"""

import json
import logging
import re
import time

from fastapi.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.services.llm_service import LLMService

logger = logging.getLogger("app.personal_analysis")

SCENE_CHAPTER = "个人书分析"
SCENE_REPORT = "个人书报告"

VALID_LEVELS = ("A1", "A2", "B1", "B2", "C1", "C2")

CHAPTER_SYSTEM_PROMPT = (
    "You are an English reading difficulty analyst for Chinese learners of English. "
    "You are given local text statistics of one book chapter and a representative "
    "excerpt of the chapter text. Your conclusions must be consistent with the "
    "provided statistics. Respond with ONLY a JSON object, no markdown fences."
)

CHAPTER_USER_TEMPLATE = """Analyze this English book chapter for Chinese learners.

Chapter title: {title}
Local statistics (computed by code, trust these numbers):
- word count: {word_count}
- unique words: {unique_word_count}
- average sentence length (words): {avg_sentence_len}
- long sentence ratio (>25 words): {long_ratio}
- vocabulary level distribution (CEFR wordlist, unknown = no reliable data): {level_dist}
- grammar feature counts (heuristic regex): {grammar_counts}

Representative excerpt (first part of the chapter):
---
{excerpt}
---

Return a JSON object with EXACTLY these keys:
{{
  "difficulty_level": "one of A1/A2/B1/B2/C1/C2 (the chapter's overall CEFR reading level)",
  "difficulty_score": <integer 0-100, higher = harder, consistent with difficulty_level>,
  "grammar_focus": [
    {{
      "pattern": "<name of the main difficult grammar pattern in this chapter, in Chinese>",
      "example": "<one real sentence from the excerpt showing it>",
      "explanation": "<1-2 sentence explanation in Chinese for learners>"
    }}
  ],
  "chapter_summary": "<2-3 sentence summary of the chapter content, in Chinese>",
  "reading_suggestion": "<1-2 sentences of practical reading advice for this chapter, in Chinese>"
}}

Constraints:
- grammar_focus: at most 3 items; only include patterns that actually appear in the excerpt; [] if none
- "example" must be a real quote from the excerpt, verbatim, max 200 chars
- Do NOT invent CEFR levels for individual words; use the provided distribution only
- Output ONLY the JSON object."""

REPORT_SYSTEM_PROMPT = (
    "You are an English reading difficulty analyst for Chinese learners of English. "
    "You are given the aggregated statistics of a whole book and the per-chapter "
    "difficulty results. Respond with ONLY a JSON object, no markdown fences."
)

REPORT_USER_TEMPLATE = """Write whole-book reading advice for a Chinese learner of English.

Book title: {title}
Aggregated statistics (computed by code, trust these numbers):
- total word count: {total_words}
- overall difficulty score (0-100, weighted average of chapters): {score}
- overall level: {level}
- chapter difficulty distribution (level: chapter count): {chapter_dist}
- vocabulary level distribution (unknown = no reliable data): {vocab_dist}
- grammar feature totals (heuristic counts): {grammar_counts}

Return a JSON object with EXACTLY these keys:
{{
  "reading_recommendations": [
    "<3-5 practical reading suggestions in Chinese, each 1-2 sentences, "
    "specific to this book's difficulty profile; e.g. which chapters are harder, "
    "what vocabulary/grammar to prepare, suitable reader level>"
  ]
}}

Output ONLY the JSON object."""

# 期望的章节 JSON 结构校验规则
class ChapterAnalysisError(Exception):
    """LLM 章节分析输出异常（JSON 不合法或字段缺失），调用方据此标记该章失败"""


def _extract_json(raw: str) -> dict:
    """从 LLM 输出中提取 JSON 对象：容忍 markdown 围栏与前后杂文本"""
    text = raw.strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    # 兜底：取第一个 { 到最后一个 } 之间的内容
    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass
    raise ChapterAnalysisError("LLM 输出不是合法 JSON")


def validate_chapter_result(data: dict) -> dict:
    """严格校验章节分析结果；不符合结构直接抛错，绝不落库污染数据"""
    level = data.get("difficulty_level")
    if not isinstance(level, str) or level.strip().upper() not in VALID_LEVELS:
        raise ChapterAnalysisError(f"difficulty_level 非法：{level!r}")
    level = level.strip().upper()

    score = data.get("difficulty_score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ChapterAnalysisError(f"difficulty_score 非数字：{score!r}")
    score = float(score)
    if not 0 <= score <= 100:
        raise ChapterAnalysisError(f"difficulty_score 超出 0-100：{score}")

    focus = data.get("grammar_focus", [])
    if not isinstance(focus, list):
        raise ChapterAnalysisError("grammar_focus 不是数组")
    cleaned_focus = []
    for item in focus[:3]:
        if not isinstance(item, dict):
            raise ChapterAnalysisError("grammar_focus 元素不是对象")
        pattern = str(item.get("pattern") or "").strip()[:120]
        example = str(item.get("example") or "").strip()[:200]
        explanation = str(item.get("explanation") or "").strip()[:300]
        if not pattern or not example:
            raise ChapterAnalysisError("grammar_focus 缺少 pattern/example")
        cleaned_focus.append({"pattern": pattern, "example": example, "explanation": explanation})

    summary = str(data.get("chapter_summary") or "").strip()[:600]
    suggestion = str(data.get("reading_suggestion") or "").strip()[:400]
    if not summary:
        raise ChapterAnalysisError("chapter_summary 为空")

    return {
        "difficulty_level": level,
        "difficulty_score": round(score, 1),
        "grammar_focus": cleaned_focus,
        "chapter_summary": summary,
        "reading_suggestion": suggestion,
    }


def validate_report_result(data: dict) -> list[str]:
    """校验全书报告的阅读建议；不合法返回空列表（由规则兜底生成）"""
    recs = data.get("reading_recommendations")
    if not isinstance(recs, list):
        return []
    out = []
    for item in recs:
        text = str(item or "").strip()[:400]
        if text:
            out.append(text)
    return out[:5]


class AnalysisLLMClient:
    """分析专用 LLM 客户端：复用 LLMService 的请求与用量流水记录"""

    def __init__(self):
        self._llm = LLMService()

    async def _chat_json(
        self, user_id: int, scene: str, system_prompt: str, user_content: str
    ) -> tuple[dict, dict]:
        """调用 LLM 并解析 JSON。返回 (解析结果, 用量流水)。校验 token 上限。"""
        settings = get_settings()
        payload = LLMService._build_payload(system_prompt, user_content)
        payload["temperature"] = 0.3
        payload["max_tokens"] = settings.PERSONAL_ANALYSIS_LLM_MAX_TOKENS
        payload["response_format"] = {"type": "json_object"}

        t0 = time.monotonic()
        raw = await run_in_threadpool(self._llm._request_chat, payload, scene)
        duration_ms = int((time.monotonic() - t0) * 1000)

        entry = self._llm.usage_log[-1] if self._llm.usage_log else {}
        usage = {
            "user_id": user_id,
            "scene": scene,
            "model": entry.get("model") or settings.DEEPSEEK_MODEL,
            "prompt_tokens": entry.get("prompt_tokens") or 0,
            "completion_tokens": entry.get("completion_tokens") or 0,
            "duration_ms": duration_ms,
        }
        return _extract_json(raw), usage

    async def analyze_chapter(
        self, user_id: int, title: str, stats: dict, excerpt: str
    ) -> tuple[dict, dict]:
        """章节分析：本地统计注入 prompt，输出严格校验。失败自动重试一次。"""
        dist = stats["vocabulary_level_distribution"]
        grammar_counts = {
            name: data.get("count", 0)
            for name, data in stats["grammar_features"].items()
        }
        user_content = CHAPTER_USER_TEMPLATE.format(
            title=title,
            word_count=stats["word_count"],
            unique_word_count=stats["unique_word_count"],
            avg_sentence_len=stats["average_sentence_length"],
            long_ratio=stats["long_sentence_ratio"],
            level_dist=json.dumps(dist, ensure_ascii=False),
            grammar_counts=json.dumps(grammar_counts, ensure_ascii=False),
            excerpt=excerpt[: get_settings().PERSONAL_ANALYSIS_MAX_LLM_CHARS],
        )
        last_err: Exception | None = None
        for attempt in range(2):
            try:
                data, usage = await self._chat_json(
                    user_id, SCENE_CHAPTER, CHAPTER_SYSTEM_PROMPT, user_content
                )
                return validate_chapter_result(data), usage
            except Exception as exc:  # JSON 不合法 / 网络异常 → 重试一次
                last_err = exc
                logger.warning("章节分析 LLM 调用失败（第 %d 次）：%s", attempt + 1, exc)
        raise ChapterAnalysisError(str(last_err) or "LLM 章节分析失败") from last_err

    async def summarize_book(
        self,
        user_id: int,
        title: str,
        agg: dict,
        level: str,
        score: float,
        chapter_dist: dict,
    ) -> tuple[list[str], dict]:
        """全书阅读建议（单次调用）。输出不合法时返回空列表，由调用方规则兜底。"""
        user_content = REPORT_USER_TEMPLATE.format(
            title=title,
            total_words=agg["total_word_count"],
            score=score,
            level=level,
            chapter_dist=json.dumps(chapter_dist, ensure_ascii=False),
            vocab_dist=json.dumps(agg["vocabulary_level_distribution"], ensure_ascii=False),
            grammar_counts=json.dumps(
                {k: v.get("count", 0) for k, v in agg["main_grammar_features"].items()},
                ensure_ascii=False,
            ),
        )
        data, usage = await self._chat_json(
            user_id, SCENE_REPORT, REPORT_SYSTEM_PROMPT, user_content
        )
        return validate_report_result(data), usage


# 难度分数 → CEFR 等级（本地规则，全书报告的 overall_level 与章节分布一致性靠它保证）
def level_from_score(score: float) -> str:
    bands = ((20, "A1"), (40, "A2"), (60, "B1"), (75, "B2"), (88, "C1"))
    for ceiling, level in bands:
        if score < ceiling:
            return level
    return "C2"
