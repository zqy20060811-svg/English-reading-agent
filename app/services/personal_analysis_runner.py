"""个人书籍 AI 全书分析后台执行器。

风格与 ingest_service 保持一致（DB 落库 + asyncio 后台 + 原子领取 + 启动恢复），
但按个人书籍分析的特点独立设计：

- 按章节顺序执行：每完成一章立即提交该章结果 + 更新任务进度（一个事务）
- 某章失败记录失败并继续后面的章节；全部结束后若仍有失败章节，任务标 failed
  （重试时只跑失败章节，已完成章节按 analysis_version 跳过不重复分析）
- 取消感知：每章开始前检查任务状态，cancelled / 任务行被删（书籍删除级联）即停止
- 本地统计放线程池；LLM 调用复用 LLMService（内部已走线程池）
- 每次 LLM 调用写 llm_usage_log（含 duration_ms 耗时）
- 不依赖进程内存状态，任务进度全部持久化在数据库

阅读解耦保证：本模块只写分析三张表，不触碰 personal_books / chapters / progress，
任务失败不影响原文与阅读进度。
"""

import asyncio
import logging
import traceback
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.database import AsyncSessionLocal
from app.models.llm_usage import LLMUsageLog
from app.models.personal_analysis import (
    PersonalAnalysisTask,
    PersonalBookAnalysis,
    PersonalChapterAnalysis,
)
from app.models.personal_book import PersonalBook
from app.models.personal_book_chapter import PersonalBookChapter
from app.services import text_statistics
from app.services.personal_analysis_llm import (
    AnalysisLLMClient,
    ChapterAnalysisError,
    level_from_score,
)

logger = logging.getLogger("app.personal_analysis")

# 后台任务句柄（进程内），持有强引用避免被 GC
_BG_TASKS: set[asyncio.Task] = set()

# 每章分析的最大失败重试轮数（章节级：本地统计 + LLM 已内置一次 JSON 重试）
_STALE_HOURS = get_settings().PERSONAL_ANALYSIS_STALE_HOURS


def _now():
    return datetime.now(timezone.utc)


def schedule_analysis(task_id: int) -> None:
    """调度后台执行（fire-and-forget，异常记录在任务行内）"""
    bg = asyncio.create_task(_run(task_id))
    _BG_TASKS.add(bg)
    bg.add_done_callback(_BG_TASKS.discard)


async def recover_interrupted_analyses() -> list[int]:
    """应用启动时恢复中断任务，返回需重新调度的 pending 任务 id 列表。

    - running → pending：章节结果已逐章落库，续跑天然跳过已完成章节，
      无需像 ingest 一样标 failed（章节级幂等，重跑安全）
    - pending 保持不变，由调用方重新调度（领取是原子的，重复调度安全）
    """
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(PersonalAnalysisTask)
            .where(PersonalAnalysisTask.status == "running")
            .values(status="pending", error_message=None, updated_at=_now())
        )
        result = await db.execute(
            select(PersonalAnalysisTask.id)
            .where(PersonalAnalysisTask.status == "pending")
            .order_by(PersonalAnalysisTask.id)
        )
        pending_ids = list(result.scalars().all())
        await db.commit()
    return pending_ids


async def _get_task(db: AsyncSession, task_id: int) -> PersonalAnalysisTask | None:
    """读取任务行；不存在（书籍删除级联）返回 None"""
    return await db.get(PersonalAnalysisTask, task_id)


async def _check_task_alive(db: AsyncSession, task_id: int) -> bool:
    """每章开始前检查：任务仍存在且处于 running 状态才继续执行"""
    task = await _get_task(db, task_id)
    return task is not None and task.status == "running"


async def _record_usage(db: AsyncSession, usage: dict) -> None:
    """LLM 用量落库（旁路数据，失败静默不阻断分析）"""
    try:
        db.add(LLMUsageLog(**usage))
    except Exception as exc:
        logger.warning("LLM 用量记录失败：%s", exc)


def _difficulty_score_fallback(stats: dict) -> float:
    """LLM 不可用时的本地启发式难度分（0-100）：
    词汇等级分布 + 平均句长 + 长句比例的加权组合。
    """
    dist = stats["vocabulary_level_distribution"]
    total = sum(dist.values()) or 1
    weights = {"A1": 0, "A2": 10, "B1": 25, "B2": 45, "C1": 65, "C2": 85, "unknown": 25}
    vocab_score = sum(dist[lv] * w for lv, w in weights.items()) / total
    # 句长贡献：平均 20 词左右记 20 分，长句比例贡献最多 15 分
    sentence_score = min(stats["average_sentence_length"], 30) + stats["long_sentence_ratio"] * 15
    return round(min(vocab_score * 0.65 + sentence_score * 0.35, 100), 1)


async def _run(task_id: int) -> None:
    """任务执行体：pending → running → completed / failed

    独立数据库会话：任务生命周期跨越请求边界，不能复用请求级会话。
    """
    client = AnalysisLLMClient()
    settings = get_settings()

    async with AsyncSessionLocal() as db:
        # 原子领取：仅当任务仍处于 pending 时置为 running，
        # 重复调度/多进程同时调度时后领取者 rowcount=0 直接返回
        result = await db.execute(
            update(PersonalAnalysisTask)
            .where(PersonalAnalysisTask.id == task_id, PersonalAnalysisTask.status == "pending")
            .values(status="running", started_at=_now(), error_message=None, updated_at=_now())
        )
        await db.commit()
        if result.rowcount == 0:
            return

        # 读取书籍元数据
        row = await db.execute(
            select(PersonalAnalysisTask, PersonalBook)
            .join(PersonalBook, PersonalBook.id == PersonalAnalysisTask.personal_book_id)
            .where(PersonalAnalysisTask.id == task_id)
        )
        got = row.first()
        if got is None:
            await _fail_task(db, task_id, "书籍不存在或已被删除")
            return
        task, book = got
        user_id, book_id = task.user_id, task.personal_book_id
        version = settings.PERSONAL_ANALYSIS_VERSION
        total = book.chapter_count

        # 初始化进度（总章数以章节表实际行数为准）
        chapters_rows = await db.execute(
            select(PersonalBookChapter.chapter_index)
            .where(PersonalBookChapter.personal_book_id == book_id)
            .order_by(PersonalBookChapter.chapter_index)
        )
        chapter_indexes = list(chapters_rows.scalars().all())
        total = len(chapter_indexes)
        task.total_chapters = total
        completed = failed = 0
        last_error: str | None = None
        chapter_results: list[dict] = []
        await db.commit()

        try:
            for idx in chapter_indexes:
                # 每章开始前检查取消/删除：非 running 状态立即静默停止
                await db.refresh(task)
                if task.status != "running":
                    return

                # 已完成章节（同版本）跳过：续跑/重试不重复分析
                existing = await db.execute(
                    select(PersonalChapterAnalysis).where(
                        PersonalChapterAnalysis.personal_book_id == book_id,
                        PersonalChapterAnalysis.chapter_index == idx,
                        PersonalChapterAnalysis.analysis_version == version,
                    )
                )
                prev = existing.scalar_one_or_none()
                if prev is not None:
                    completed += 1
                    chapter_results.append(_result_to_stats(prev))
                    task.current_chapter_index = idx
                    task.completed_chapters = completed
                    await db.commit()
                    continue

                task.current_chapter_index = idx
                await db.commit()

                # 读取章节正文
                ch = await db.execute(
                    select(PersonalBookChapter).where(
                        PersonalBookChapter.personal_book_id == book_id,
                        PersonalBookChapter.chapter_index == idx,
                    )
                )
                chapter = ch.scalar_one_or_none()
                if chapter is None:
                    completed += 1  # 章节缺失视为跳过（不应发生：total 取自章节表）
                    continue

                try:
                    result_data, usage = await _analyze_one_chapter(
                        client, user_id, chapter, settings
                    )
                    await _save_chapter_result(
                        db, user_id, book_id, idx, version, result_data, usage
                    )
                    completed += 1
                    chapter_results.append(result_data)
                    task.completed_chapters = completed
                    task.failed_chapters = failed
                except Exception as exc:  # 单章失败不阻塞后续章节
                    failed += 1
                    last_error = f"第 {idx} 章分析失败：{exc}"
                    logger.warning("任务 #%d %s", task_id, last_error)
                    task.failed_chapters = failed
                    task.error_message = last_error
                await db.commit()

            # 全部章节处理完毕
            await db.refresh(task)
            if task.status != "running":
                return

            if completed >= total:
                # 汇总全书报告（本地聚合；有 Key 时由 LLM 生成阅读建议，否则规则兜底）
                agg = text_statistics.aggregate_book_stats(chapter_results)
                score = _weighted_score(chapter_results, total)
                level = level_from_score(score)
                if settings.DEEPSEEK_API_KEY:
                    recommendations, report_usage = await _book_recommendations(
                        client, user_id, book.title, agg, level, score,
                        _chapter_level_dist(chapter_results),
                    )
                    await _record_usage(db, report_usage)
                else:
                    recommendations = _rule_based_recommendations(agg, level)
                from sqlalchemy.dialects.postgresql import insert as pg_insert

                report_values = {
                    "user_id": user_id,
                    "personal_book_id": book_id,
                    "overall_level": level,
                    "difficulty_score": score,
                    "total_word_count": agg["total_word_count"],
                    "chapter_difficulty_distribution": _chapter_level_dist(chapter_results),
                    "vocabulary_level_distribution": agg["vocabulary_level_distribution"],
                    "main_grammar_features": agg["main_grammar_features"],
                    "reading_recommendations": recommendations,
                    "analysis_version": version,
                    "completed_at": _now(),
                    "updated_at": _now(),
                }
                await db.execute(
                    pg_insert(PersonalBookAnalysis).values(**report_values)
                    .on_conflict_do_update(
                        constraint="uq_personal_book_analysis",
                        set_=report_values,
                    )
                )
                task.status = "completed"
                task.completed_chapters = completed
                task.failed_chapters = 0
                task.error_message = None
                task.current_chapter_index = None
                task.completed_at = _now()
                await db.commit()
                logger.info(
                    "个人书分析任务 #%d 完成：%s（%d 章，难度 %s）", task_id, book.title, total, level
                )
            else:
                task.status = "failed"
                task.error_message = last_error or f"{failed} 个章节分析失败，可重试（已完成的章节不会重复分析）"
                await db.commit()
        except Exception as exc:
            # 执行体级异常（数据库/意外错误）：标记失败，可重试续跑
            await db.rollback()
            await _fail_task(
                db, task_id,
                f"{exc}\n{traceback.format_exc()[-800:]}",
            )


def _result_to_stats(row: PersonalChapterAnalysis) -> dict:
    """把已落库的章节结果转回 aggregate 需要的统计结构（续跑时补齐汇总输入）"""
    return {
        "word_count": row.word_count,
        "difficulty_level": row.difficulty_level,
        "difficulty_score": row.difficulty_score,
        "vocabulary_level_distribution": dict(row.vocabulary_level_distribution or {}),
        "grammar_features": dict(row.grammar_features or {}),
        "average_sentence_length": row.average_sentence_length,
        "long_sentence_ratio": row.long_sentence_ratio,
    }


def _weighted_score(chapter_results: list[dict], total: int) -> float:
    """按章节词数加权的全书难度分"""
    if not chapter_results:
        return 0.0
    weighted = sum(r["difficulty_score"] * r["word_count"] for r in chapter_results)
    words = sum(r["word_count"] for r in chapter_results)
    return round(weighted / words, 1) if words else round(
        sum(r["difficulty_score"] for r in chapter_results) / max(total, 1), 1
    )


def _chapter_level_dist(chapter_results: list[dict]) -> dict[str, int]:
    dist: dict[str, int] = {lv: 0 for lv in ("A1", "A2", "B1", "B2", "C1", "C2")}
    for r in chapter_results:
        lv = r.get("difficulty_level")
        if lv in dist:
            dist[lv] += 1
    return dist


async def _analyze_one_chapter(
    client: AnalysisLLMClient, user_id: int, chapter, settings
) -> tuple[dict, dict]:
    """单章流水线：本地统计（线程池）→ LLM 分析 → 结果结构组装。

    - LLM 已配置但调用/解析失败：该章视为失败并抛出 ChapterAnalysisError，
      由外层记为失败章节（支持重试），绝不把错误结构写入数据库
    - LLM 未配置（离线环境）：降级为纯本地分析（难度分与等级用启发式规则，
      grammar_focus 仅保留规则初筛结果，不编造 LLM 结论）
    """
    stats = await asyncio.to_thread(text_statistics.analyze_chapter_text, chapter.content)
    excerpt = chapter.content[: settings.PERSONAL_ANALYSIS_MAX_LLM_CHARS]

    llm_result: dict | None = None
    usage: dict | None = None
    if settings.DEEPSEEK_API_KEY:
        llm_result, usage = await client.analyze_chapter(
            user_id, chapter.title, stats, excerpt
        )
        grammar_features = {
            "local_rules": stats["grammar_features"],
            "llm_focus": llm_result["grammar_focus"],
        }
    else:
        grammar_features = {"local_rules": stats["grammar_features"]}

    if llm_result is not None:
        level = llm_result["difficulty_level"]
        score = llm_result["difficulty_score"]
        summary = llm_result["chapter_summary"]
        suggestion = llm_result["reading_suggestion"]
    else:
        score = _difficulty_score_fallback(stats)
        level = level_from_score(score)
        summary = ""
        suggestion = ""

    result = {**stats}
    result.update({
        "grammar_features": grammar_features,
        "difficulty_level": level,
        "difficulty_score": score,
        "chapter_summary": summary,
        "reading_suggestion": suggestion,
    })
    return result, usage or {}


async def _save_chapter_result(
    db: AsyncSession, user_id: int, book_id: int, chapter_index: int,
    version: int, result_data: dict, usage: dict | None,
) -> None:
    """章节结果 + 用量一起落库（ON CONFLICT 原子写，幂等）"""
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    values = {
        "user_id": user_id,
        "personal_book_id": book_id,
        "chapter_index": chapter_index,
        "word_count": result_data["word_count"],
        "unique_word_count": result_data["unique_word_count"],
        "average_sentence_length": result_data["average_sentence_length"],
        "long_sentence_ratio": result_data["long_sentence_ratio"],
        "vocabulary_level_distribution": result_data["vocabulary_level_distribution"],
        "vocabulary_statistics": result_data["vocabulary_statistics"],
        "grammar_features": result_data["grammar_features"],
        "difficulty_level": result_data["difficulty_level"],
        "difficulty_score": result_data["difficulty_score"],
        "chapter_summary": result_data["chapter_summary"],
        "reading_suggestion": result_data["reading_suggestion"],
        "analysis_version": version,
        "updated_at": _now(),
    }
    await db.execute(
        pg_insert(PersonalChapterAnalysis).values(**values)
        .on_conflict_do_update(
            constraint="uq_personal_chapter_analysis",
            set_=values,
        )
    )
    if usage:
        await _record_usage(db, usage)


async def _book_recommendations(
    client: AnalysisLLMClient, user_id: int, title: str, agg: dict,
    level: str, score: float, chapter_dist: dict,
) -> tuple[list[str], dict]:
    """全书阅读建议：LLM 优先，输出不合法时用本地规则兜底（不编造 LLM 结论）"""
    try:
        recs, usage = await client.summarize_book(user_id, title, agg, level, score, chapter_dist)
        if recs:
            return recs, usage
        return _rule_based_recommendations(agg, level), usage
    except Exception as exc:
        logger.warning("全书建议 LLM 调用失败，使用规则兜底：%s", exc)
        usage = {
            "user_id": user_id, "scene": "个人书报告", "model": "",
            "prompt_tokens": 0, "completion_tokens": 0, "duration_ms": 0,
        }
        return _rule_based_recommendations(agg, level), usage


def _rule_based_recommendations(agg: dict, level: str) -> list[str]:
    """本地规则生成的全书阅读建议（LLM 失败时的确定性兜底）"""
    dist = agg.get("vocabulary_level_distribution", {})
    total = sum(dist.values()) or 1
    hard_ratio = (dist.get("B2", 0) + dist.get("C1", 0) + dist.get("C2", 0)) / total
    unknown_ratio = dist.get("unknown", 0) / total
    recs = [
        f"本书整体难度约为 {level}，适合当前水平相近或略高的读者阅读。",
    ]
    if hard_ratio > 0.15:
        recs.append(
            f"中高级词汇（B2 及以上）占比约 {hard_ratio:.0%}，建议先浏览每章分析的词汇分布，"
            "提前熟悉高频难点词。"
        )
    if unknown_ratio > 0.2:
        recs.append(
            f"约 {unknown_ratio:.0%} 的词不在基础 CEFR 词典内（多为专有名词与低频词），"
            "遇到时结合上下文判断，不必逐个查词。"
        )
    if agg.get("long_sentence_ratio", 0) > 0.1:
        recs.append("长句比例较高，遇到超过 25 词的句子时建议先找主谓结构再拆分修饰成分。")
    if agg.get("average_sentence_length", 0) < 12:
        recs.append("本书句子普遍较短，适合练习流利阅读与意群识别。")
    recs.append("建议每天阅读 1-2 章，结合章节摘要回顾前一天的内容以巩固词汇。")
    return recs[:5]


async def _fail_task(db: AsyncSession, task_id: int, message: str) -> None:
    """任务级失败落库（截断 traceback，可重试）"""
    async with AsyncSessionLocal() as fail_db:
        await fail_db.execute(
            update(PersonalAnalysisTask)
            .where(
                PersonalAnalysisTask.id == task_id,
                PersonalAnalysisTask.status.in_(("running", "pending")),
            )
            .values(
                status="failed",
                error_message=message[-2000:],
                completed_at=_now(),
                updated_at=_now(),
            )
        )
        await fail_db.commit()


async def mark_stale_running_failed() -> int:
    """懒惰兜底：running 超过阈值小时数视为挂死，标记失败（可重试续跑）"""
    cutoff = _now() - timedelta(hours=_STALE_HOURS)
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            update(PersonalAnalysisTask)
            .where(PersonalAnalysisTask.status == "running", PersonalAnalysisTask.started_at < cutoff)
            .values(
                status="failed",
                error_message=f"任务执行超过 {_STALE_HOURS} 小时未完成，已自动标记失败，可重试续跑",
                completed_at=_now(),
                updated_at=_now(),
            )
        )
        await db.commit()
    return result.rowcount
