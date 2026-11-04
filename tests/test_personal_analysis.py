"""个人电子书 AI 全书预分析（阶段B）测试。

- TestTextStatistics：本地统计（纯单元，不依赖词典文件）
- TestAnalysisLLM：LLM JSON 校验与等级映射（纯单元）
- TestPersonalAnalysisDB：任务生命周期集成测试（需要 PostgreSQL）

运行：python -m pytest tests/test_personal_analysis.py -v
"""

import asyncio
import io
import json
import uuid
import zipfile

import pytest
from fastapi import HTTPException

from app.services import cefr_lexicon, personal_analysis_llm
from app.services.personal_analysis_llm import (
    ChapterAnalysisError,
    level_from_score,
    validate_chapter_result,
)


# ================= 复用阶段A的测试 EPUB =================

from tests.test_personal_books import _build_epub  # noqa: E402


# ================= 本地统计（纯单元） =================


class TestTextStatistics:
    def test_tokenize_and_word_count(self):
        from app.services.text_statistics import tokenize

        tokens = tokenize("Don't stop believing, it's the 1980s!")
        assert len(tokens) == 6  # Don't / stop / believing / it's / the / 1980s → s 单独不算词
        assert "believing" in tokens

    def test_sentence_stats(self):
        from app.services.text_statistics import sentence_stats

        text = "Short one. " + "word " * 30 + "here. Medium length sentence follows."
        avg, long_ratio, sentences = sentence_stats(text)
        assert len(sentences) == 3
        assert avg > 8
        assert 0 < long_ratio < 1  # 30 词的句子是长句

    def test_sentence_stats_empty(self):
        from app.services.text_statistics import sentence_stats

        assert sentence_stats("") == (0.0, 0.0, [])

    def test_vocab_distribution_uses_injected_lexicon(self, monkeypatch):
        from app.services.text_statistics import classify_tokens

        monkeypatch.setattr(cefr_lexicon, "load_lexicon", lambda: {"fox": "B2"})
        counts = classify_tokens(["Fox", "foxes", "the"])
        # fox 命中词典；foxes 未命中（无词形还原，保守策略）→ unknown
        assert counts["B2"] == 1
        assert counts["unknown"] == 2

    def test_grammar_features_counts(self):
        from app.services.text_statistics import grammar_features, split_sentences

        text = (
            "The letter was written by John. When she arrived, he said that he was tired. "
            "If I were rich, I would travel the world. Never have I seen such a mess."
        )
        sentences = split_sentences(text)
        feats = grammar_features(text, sentences)
        assert feats["passive_voice"]["count"] >= 1
        assert feats["adverbial_clause"]["count"] >= 1
        assert feats["noun_clause"]["count"] >= 1
        assert feats["inversion_front"]["count"] == 1
        assert feats["passive_voice"]["examples"]  # 有例句采样

    def test_aggregate_book_stats(self):
        from app.services.text_statistics import aggregate_book_stats

        chapters = [
            {
                "word_count": 100,
                "average_sentence_length": 10,
                "long_sentence_ratio": 0.1,
                "vocabulary_level_distribution": {"A1": 80, "unknown": 20},
                "grammar_features": {"local_rules": {"passive_voice": {"count": 3}}},
            },
            {
                "word_count": 300,
                "average_sentence_length": 20,
                "long_sentence_ratio": 0.3,
                "vocabulary_level_distribution": {"A1": 100, "B1": 200},
                "grammar_features": {"local_rules": {"passive_voice": {"count": 1}}},
            },
        ]
        agg = aggregate_book_stats(chapters)
        assert agg["total_word_count"] == 400
        assert agg["vocabulary_level_distribution"]["A1"] == 180
        assert agg["main_grammar_features"]["passive_voice"]["count"] == 4
        # 按词数加权：100*10 + 300*20 = 7000 / 400 = 17.5
        assert agg["average_sentence_length"] == 17.5


# ================= LLM JSON 校验（纯单元） =================


_VALID = {
    "difficulty_level": "b2",
    "difficulty_score": 62,
    "grammar_focus": [
        {"pattern": "定语从句", "example": "the book which I read", "explanation": "解释"}
    ],
    "chapter_summary": "本章讲述了主角的冒险。",
    "reading_suggestion": "注意定语从句。",
}


class TestAnalysisLLMValidation:
    def test_valid_result_normalized(self):
        out = validate_chapter_result(_VALID)
        assert out["difficulty_level"] == "B2"
        assert out["difficulty_score"] == 62.0
        assert len(out["grammar_focus"]) == 1

    def test_invalid_level_rejected(self):
        with pytest.raises(ChapterAnalysisError):
            validate_chapter_result({**_VALID, "difficulty_level": "Z9"})

    def test_score_out_of_range_rejected(self):
        with pytest.raises(ChapterAnalysisError):
            validate_chapter_result({**_VALID, "difficulty_score": 150})

    def test_missing_summary_rejected(self):
        with pytest.raises(ChapterAnalysisError):
            validate_chapter_result({**_VALID, "chapter_summary": "  "})

    def test_grammar_focus_not_list_rejected(self):
        with pytest.raises(ChapterAnalysisError):
            validate_chapter_result({**_VALID, "grammar_focus": "x"})

    def test_extract_json_with_fences(self):
        raw = "```json\n" + json.dumps(_VALID) + "\n```"
        from app.services.personal_analysis_llm import _extract_json

        assert _extract_json(raw)["difficulty_level"].upper() == "B2"

    def test_extract_json_with_noise(self):
        raw = "Sure! Here is my analysis:\n" + json.dumps(_VALID) + "\nHope it helps."
        from app.services.personal_analysis_llm import _extract_json

        assert _extract_json(raw)["difficulty_score"] == 62

    def test_extract_json_garbage_raises(self):
        from app.services.personal_analysis_llm import _extract_json

        with pytest.raises(ChapterAnalysisError):
            _extract_json("completely not json")

    def test_report_recommendations_validated(self):
        from app.services.personal_analysis_llm import validate_report_result

        assert validate_report_result({"reading_recommendations": ["a", "", "b"]}) == ["a", "b"]
        assert validate_report_result({"reading_recommendations": "bad"}) == []
        assert validate_report_result({}) == []

    def test_level_from_score_bands(self):
        assert level_from_score(10) == "A1"
        assert level_from_score(30) == "A2"
        assert level_from_score(50) == "B1"
        assert level_from_score(70) == "B2"
        assert level_from_score(85) == "C1"
        assert level_from_score(95) == "C2"


# ================= 数据库集成 =================

DB_READY = None


def _db_available() -> bool:
    global DB_READY
    if DB_READY is not None:
        return DB_READY

    async def _ping():
        from app.db.database import engine

        await engine.dispose()
        async with engine.connect() as conn:
            await conn.execute(__import__("sqlalchemy").text("SELECT 1"))

    try:
        asyncio.run(_ping())
        DB_READY = True
    except Exception:
        DB_READY = False
    return DB_READY


requires_db = pytest.mark.skipif(
    not _db_available(), reason="PostgreSQL 不可用，跳过个人书分析数据库测试"
)


def _run(coro):
    async def _wrap():
        from app.db.database import engine

        await engine.dispose()
        await coro

    return asyncio.run(_wrap())


async def _make_user(db):
    from app.models.user import User

    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f"pan_{suffix}",
        email=f"pan_{suffix}@test.local",
        hashed_password="x",
        email_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


class FakeUsage:
    """记录 fake LLM 的调用流水（与真实 usage dict 同结构）"""

    @staticmethod
    def entry(user_id, scene="个人书分析"):
        return {
            "user_id": user_id, "scene": scene, "model": "fake-model",
            "prompt_tokens": 100, "completion_tokens": 50, "duration_ms": 10,
        }


async def _setup(monkeypatch, tmp_path, *, chapter_fail_titles=(), garbage=False,
                 llm_calls=None, recs=None):
    """构造用户 + 两章书籍；monkeypatch 掉 LLM 与后台调度。

    返回 (user, book, service, runner)。
    """
    from app.core.config import get_settings
    from app.db.database import AsyncSessionLocal
    from app.services import personal_analysis_runner as runner
    from app.services import personal_analysis_service as pa_service
    from app.services.personal_book_service import PersonalBookService
    from app.services.personal_analysis_llm import AnalysisLLMClient

    settings = get_settings()
    monkeypatch.setattr(settings, "PERSONAL_BOOKS_DIR", str(tmp_path))
    monkeypatch.setattr(pa_service, "schedule_analysis", lambda tid: None)

    async with AsyncSessionLocal() as db:
        user = await _make_user(db)
        service = PersonalBookService(db)
        book, _ = await service.create_book(user, "book.epub", _build_epub())

    async def fake_analyze_chapter(self, user_id, title, stats, excerpt):
        if llm_calls is not None:
            llm_calls.append(title)
        if title in chapter_fail_titles:
            raise ChapterAnalysisError("fake failure")
        if garbage:
            raise ChapterAnalysisError("LLM 输出不是合法 JSON")
        return {
            "difficulty_level": "B1",
            "difficulty_score": 45.0,
            "grammar_focus": [
                {"pattern": "被动语态", "example": "The letter was written by John.",
                 "explanation": "be + 过去分词"}
            ],
            "chapter_summary": f"{title} 的摘要。",
            "reading_suggestion": "保持原速阅读即可。",
        }, FakeUsage.entry(user_id)

    async def fake_summarize_book(self, user_id, title, agg, level, score, chapter_dist):
        if llm_calls is not None:
            llm_calls.append("__report__")
        if recs is not None:
            return recs, FakeUsage.entry(user_id, "个人书报告")
        return [
            f"本书整体难度 {level}，建议精读。",
            "先通读章节摘要，再逐章阅读。",
        ], FakeUsage.entry(user_id, "个人书报告")

    monkeypatch.setattr(AnalysisLLMClient, "analyze_chapter", fake_analyze_chapter)
    monkeypatch.setattr(AnalysisLLMClient, "summarize_book", fake_summarize_book)
    return user, book, service, runner


@requires_db
class TestPersonalAnalysisDB:
    def test_upload_auto_creates_task_and_completes(self, tmp_path, monkeypatch):
        """上传后 ensure_task 创建任务 → 两章分析完成 → 报告生成（正常完成一本多章节书）"""
        llm_calls: list = []

        async def main():
            from sqlalchemy import func, select

            from app.db.database import AsyncSessionLocal
            from app.models.personal_analysis import (
                PersonalAnalysisTask, PersonalBookAnalysis, PersonalChapterAnalysis,
            )
            from app.services.personal_analysis_service import PersonalAnalysisService

            user, book, _service, runner = await _setup(
                monkeypatch, tmp_path, llm_calls=llm_calls
            )
            async with AsyncSessionLocal() as db:
                analysis = PersonalAnalysisService(db)
                # 上传自动触发的语义：ensure_task 创建任务
                task = await analysis.ensure_task(user, book.id)
                assert task.status == "pending"
                assert task.total_chapters == 2
                task_id = task.id

            # 执行后台任务（直接调用执行体）
            await runner._run(task_id)

            async with AsyncSessionLocal() as db:
                task = await db.get(PersonalAnalysisTask, task_id)
                assert task.status == "completed"
                assert task.completed_chapters == 2
                assert task.failed_chapters == 0
                assert task.completed_at is not None

                chapters = (await db.execute(
                    select(PersonalChapterAnalysis)
                    .where(PersonalChapterAnalysis.personal_book_id == book.id)
                    .order_by(PersonalChapterAnalysis.chapter_index)
                )).scalars().all()
                assert len(chapters) == 2
                assert all(c.difficulty_level == "B1" for c in chapters)
                assert chapters[0].word_count > 0
                assert "local_rules" in chapters[0].grammar_features
                assert chapters[0].grammar_features["llm_focus"]

                report = (await db.execute(
                    select(PersonalBookAnalysis)
                    .where(PersonalBookAnalysis.personal_book_id == book.id)
                )).scalars().one()
                assert report.overall_level == "B1"
                assert report.difficulty_score == 45.0
                assert report.total_word_count == sum(c.word_count for c in chapters)
                assert report.chapter_difficulty_distribution["B1"] == 2
                assert len(report.reading_recommendations) >= 2

                # 每次 LLM 调用记录了用量（2 章 + 1 报告）
                from app.models.llm_usage import LLMUsageLog

                usage_count = (await db.execute(
                    select(func.count()).select_from(LLMUsageLog)
                    .where(LLMUsageLog.user_id == user.id)
                )).scalar()
                assert usage_count == 3

            # 报告接口可读
            async with AsyncSessionLocal() as db:
                out = await PersonalAnalysisService(db).get_report(user, book.id)
                assert out.overall_level == "B1"
                chapter_out = await PersonalAnalysisService(db).get_chapter_result(user, book.id, 1)
                assert chapter_out.chapter_summary.endswith("的摘要。")

        _run(main())

    def test_reading_unaffected_during_running_task(self, tmp_path, monkeypatch):
        """任务运行中：章节正文与阅读进度完全可用（阅读与分析解耦）"""

        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.personal_analysis import PersonalAnalysisTask
            from app.schemas.personal_book import PersonalProgressUpdate
            from app.services.personal_analysis_service import PersonalAnalysisService
            from app.services.personal_book_service import PersonalBookService

            user, book, pbs, runner = await _setup(monkeypatch, tmp_path)

            async with AsyncSessionLocal() as db:
                analysis = PersonalAnalysisService(db)
                task = await analysis.ensure_task(user, book.id)
                task_id = task.id

            async with AsyncSessionLocal() as db:
                # 模拟任务已领取、正在执行中
                t = await db.get(PersonalAnalysisTask, task_id)
                t.status = "running"
                t.started_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                await db.commit()

            async with AsyncSessionLocal() as db:
                pbs = PersonalBookService(db)
                # 分析进行中，阅读不受影响
                detail = await pbs.get_chapter(user, book.id, 1)
                assert detail.content
                progress = await pbs.save_progress(
                    user, book.id, PersonalProgressUpdate(
                        chapter_index=1, char_offset=5, percent=1.0, page_index=0
                    )
                )
                assert progress.percent == 1.0

        _run(main())

    def test_chapter_failure_then_retry_resumes(self, tmp_path, monkeypatch):
        """第 1 章失败不影响第 2 章；重试只跑失败章节，已完成章节不重复分析"""
        llm_calls: list = []

        async def main():
            from sqlalchemy import select

            from app.db.database import AsyncSessionLocal
            from app.models.personal_analysis import (
                PersonalAnalysisTask, PersonalChapterAnalysis,
            )
            from app.services.personal_analysis_service import PersonalAnalysisService

            user, book, _pbs, runner = await _setup(
                monkeypatch, tmp_path, chapter_fail_titles=("Chapter One",), llm_calls=llm_calls
            )
            async with AsyncSessionLocal() as db:
                task_id = (await PersonalAnalysisService(db).ensure_task(user, book.id)).id
            await runner._run(task_id)

            async with AsyncSessionLocal() as db:
                task = await db.get(PersonalAnalysisTask, task_id)
                assert task.status == "failed"
                assert task.completed_chapters == 1
                assert task.failed_chapters == 1
                assert "第 1 章分析失败" in task.error_message
                # 第 2 章成功、第 1 章无结果
                rows = (await db.execute(
                    select(PersonalChapterAnalysis)
                    .where(PersonalChapterAnalysis.personal_book_id == book.id)
                )).scalars().all()
                assert [r.chapter_index for r in rows] == [2]

            # LLM 报告不应被调用（章节未全部完成）
            assert "__report__" not in llm_calls
            assert llm_calls.count("Chapter Two") == 1

            # 重试：LLM 恢复正常 → 续跑
            llm_calls.clear()
            monkeypatch.setattr(
                personal_analysis_llm.AnalysisLLMClient,
                "analyze_chapter",
                await _ok_analyzer(llm_calls),
            )
            async with AsyncSessionLocal() as db:
                task = (await PersonalAnalysisService(db).ensure_task(user, book.id))
                assert task.status == "pending"  # failed → pending 续跑
                task_id = task.id
            await runner._run(task_id)

            async with AsyncSessionLocal() as db:
                task = await db.get(PersonalAnalysisTask, task_id)
                assert task.status == "completed"
                rows = (await db.execute(
                    select(PersonalChapterAnalysis)
                    .where(PersonalChapterAnalysis.personal_book_id == book.id)
                    .order_by(PersonalChapterAnalysis.chapter_index)
                )).scalars().all()
                assert [r.chapter_index for r in rows] == [1, 2]
            # 第 2 章未被重复分析（版本跳过），第 1 章新分析一次
            assert llm_calls.count("Chapter Two") == 0
            assert llm_calls.count("Chapter One") == 1
            assert "__report__" in llm_calls

        _run(main())

    def test_service_restart_resume_skips_completed(self, tmp_path, monkeypatch):
        """部分章节完成后服务重启：running → pending，续跑跳过已完成章节"""
        llm_calls: list = []

        async def main():
            from sqlalchemy import select

            from app.db.database import AsyncSessionLocal
            from app.models.personal_analysis import (
                PersonalAnalysisTask, PersonalChapterAnalysis,
            )
            from app.services.personal_analysis_runner import recover_interrupted_analyses
            from app.services.personal_analysis_service import PersonalAnalysisService

            # 第一轮：只让第 1 章成功（手动中断模拟：执行完一章后任务卡在 running）
            user, book, _pbs, runner = await _setup(monkeypatch, tmp_path, llm_calls=llm_calls)
            async with AsyncSessionLocal() as db:
                task_id = (await PersonalAnalysisService(db).ensure_task(user, book.id)).id
            await runner._run(task_id)  # 两章都成功 + 报告

            # 模拟升级分析版本后重新分析，中途崩溃：第 1 章已完成并落库，任务卡 running
            from app.core.config import get_settings
            settings = get_settings()
            monkeypatch.setattr(settings, "PERSONAL_ANALYSIS_VERSION", 2)
            async with AsyncSessionLocal() as db:
                task = await db.get(PersonalAnalysisTask, task_id)
                task.status = "running"
                task.started_at = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
                task.completed_at = None
                await db.commit()
                # 手动写入第 1 章的 v2 结果（模拟崩溃前已完成）
                ch1 = (await db.execute(
                    select(PersonalChapterAnalysis)
                    .where(
                        PersonalChapterAnalysis.personal_book_id == book.id,
                        PersonalChapterAnalysis.chapter_index == 1,
                    )
                )).scalar_one()
                ch1.analysis_version = 2
                await db.commit()

            llm_calls.clear()
            # 服务重启：running → pending 并重新调度
            pending_ids = await recover_interrupted_analyses()
            assert task_id in pending_ids
            await runner._run(task_id)

            async with AsyncSessionLocal() as db:
                task = await db.get(PersonalAnalysisTask, task_id)
                assert task.status == "completed"
                assert task.completed_chapters == 2
            # 第 1 章（v2 已存在）被跳过，没有再次调用 LLM
            assert llm_calls.count("Chapter One") == 0
            assert llm_calls.count("Chapter Two") == 1

        _run(main())

    def test_duplicate_trigger_no_concurrent_execution(self, tmp_path, monkeypatch):
        """同一本书重复触发：返回同一任务，不并发重复执行"""

        async def main():
            from sqlalchemy import select

            from app.db.database import AsyncSessionLocal
            from app.models.personal_analysis import (
                PersonalAnalysisTask, PersonalBookAnalysis, PersonalChapterAnalysis,
            )
            from app.services.personal_analysis_service import PersonalAnalysisService

            user, book, _pbs, runner = await _setup(monkeypatch, tmp_path)
            async with AsyncSessionLocal() as db:
                svc = PersonalAnalysisService(db)
                t1 = await svc.ensure_task(user, book.id)
                t2 = await svc.ensure_task(user, book.id)  # active 中重复触发
                assert t1.id == t2.id
                task_id = t1.id

            # 两次并发领取：第二次 rowcount=0 直接返回（原子领取）
            await asyncio.gather(runner._run(task_id), runner._run(task_id))

            async with AsyncSessionLocal() as db:
                task = await db.get(PersonalAnalysisTask, task_id)
                assert task.status == "completed"
                rows = (await db.execute(
                    select(PersonalChapterAnalysis)
                    .where(PersonalChapterAnalysis.personal_book_id == book.id)
                )).scalars().all()
                assert len(rows) == 2  # 每章只有一条结果
                report_rows = (await db.execute(
                    select(PersonalBookAnalysis)
                    .where(PersonalBookAnalysis.personal_book_id == book.id)
                )).scalars().all()
                assert len(report_rows) == 1

        _run(main())

    def test_cancel_stops_execution(self, tmp_path, monkeypatch):
        """取消任务：后台执行体感知后停止，剩余章节不再分析"""
        llm_calls: list = []

        async def main():
            from sqlalchemy import select

            from app.db.database import AsyncSessionLocal
            from app.models.personal_analysis import (
                PersonalAnalysisTask, PersonalChapterAnalysis,
            )
            from app.services.personal_analysis_service import PersonalAnalysisService

            user, book, _pbs, runner = await _setup(monkeypatch, tmp_path, llm_calls=llm_calls)
            async with AsyncSessionLocal() as db:
                task_id = (await PersonalAnalysisService(db).ensure_task(user, book.id)).id

            # 立即取消（任务还是 pending）→ 执行体领取时发现已取消？领取只领 pending，
            # cancelled 不是 pending → rowcount=0 → 直接返回，不执行任何章节
            async with AsyncSessionLocal() as db:
                svc = PersonalAnalysisService(db)
                task = await svc.cancel_task(user, book.id)
                assert task.status == "cancelled"

            await runner._run(task_id)

            async with AsyncSessionLocal() as db:
                task = await db.get(PersonalAnalysisTask, task_id)
                assert task.status == "cancelled"
                rows = (await db.execute(
                    select(PersonalChapterAnalysis)
                    .where(PersonalChapterAnalysis.personal_book_id == book.id)
                )).scalars().all()
                assert rows == []

        _run(main())

    def test_cancel_during_running_stops_midway(self, tmp_path, monkeypatch):
        """running 中取消：执行体在下章开始前停止"""
        llm_calls: list = []

        async def main():
            from sqlalchemy import select

            from app.db.database import AsyncSessionLocal
            from app.models.personal_analysis import PersonalAnalysisTask
            from app.services.personal_analysis_service import PersonalAnalysisService

            user, book, _pbs, runner = await _setup(monkeypatch, tmp_path, llm_calls=llm_calls)
            async with AsyncSessionLocal() as db:
                task_id = (await PersonalAnalysisService(db).ensure_task(user, book.id)).id

            # fake LLM：第 1 章分析完成后取消任务
            import app.services.personal_analysis_llm as llm_mod

            original = llm_mod.AnalysisLLMClient.analyze_chapter

            async def cancelling_analyze(self, user_id, title, stats, excerpt):
                result = await original(self, user_id, title, stats, excerpt)
                async with AsyncSessionLocal() as cdb:
                    t = await cdb.get(PersonalAnalysisTask, task_id)
                    t.status = "cancelled"
                    await cdb.commit()
                return result

            monkeypatch.setattr(llm_mod.AnalysisLLMClient, "analyze_chapter", cancelling_analyze)
            await runner._run(task_id)

            async with AsyncSessionLocal() as db:
                task = await db.get(PersonalAnalysisTask, task_id)
                assert task.status == "cancelled"
            # 只有第 1 章被分析，第 2 章未开始
            assert llm_calls == ["Chapter One"]

        _run(main())

    def test_user_isolation(self, tmp_path, monkeypatch):
        """用户 A 无法读取用户 B 的任务/报告/章节结果（统一 404）"""

        async def main():
            from app.db.database import AsyncSessionLocal
            from app.services.personal_analysis_runner import _run as _run_task
            from app.services.personal_analysis_service import PersonalAnalysisService

            user_a, book, _pbs, runner = await _setup(monkeypatch, tmp_path)
            user_b = await _make_user_in(AsyncSessionLocal)

            async with AsyncSessionLocal() as db:
                task_id = (await PersonalAnalysisService(db).ensure_task(user_a, book.id)).id
            await _run_task(task_id)

            async with AsyncSessionLocal() as db:
                svc = PersonalAnalysisService(db)
                with pytest.raises(HTTPException) as exc:
                    await svc.get_status(user_b, book.id)
                assert exc.value.status_code == 404
                with pytest.raises(HTTPException):
                    await svc.get_report(user_b, book.id)
                with pytest.raises(HTTPException):
                    await svc.get_chapter_result(user_b, book.id, 1)
                with pytest.raises(HTTPException):
                    await svc.cancel_task(user_b, book.id)
                # B 也不能触发 A 的书
                with pytest.raises(HTTPException):
                    await svc.ensure_task(user_b, book.id)

        _run(main())

    def test_delete_book_cascades_analysis_data(self, tmp_path, monkeypatch):
        """删除书籍：任务/章节结果/报告全部级联清理"""
        llm_calls: list = []

        async def main():
            from sqlalchemy import select

            from app.db.database import AsyncSessionLocal
            from app.models.personal_analysis import (
                PersonalAnalysisTask, PersonalBookAnalysis, PersonalChapterAnalysis,
            )
            from app.services.personal_analysis_service import PersonalAnalysisService
            from app.services.personal_book_service import PersonalBookService

            user, book, _pbs, runner = await _setup(monkeypatch, tmp_path)
            async with AsyncSessionLocal() as db:
                task_id = (await PersonalAnalysisService(db).ensure_task(user, book.id)).id
            await runner._run(task_id)

            async with AsyncSessionLocal() as db:
                pbs = PersonalBookService(db)
                await pbs.delete_book(user, book.id)

            async with AsyncSessionLocal() as db:
                assert (await db.execute(
                    select(PersonalAnalysisTask).where(
                        PersonalAnalysisTask.personal_book_id == book.id)
                )).scalars().all() == []
                assert (await db.execute(
                    select(PersonalChapterAnalysis).where(
                        PersonalChapterAnalysis.personal_book_id == book.id)
                )).scalars().all() == []
                assert (await db.execute(
                    select(PersonalBookAnalysis).where(
                        PersonalBookAnalysis.personal_book_id == book.id)
                )).scalars().all() == []

        _run(main())

    def test_llm_garbage_does_not_pollute_db(self, tmp_path, monkeypatch):
        """LLM 返回异常结构：该章失败，数据库无脏数据，其他章正常"""
        llm_calls: list = []

        async def main():
            from sqlalchemy import select

            from app.db.database import AsyncSessionLocal
            from app.models.personal_analysis import (
                PersonalAnalysisTask, PersonalChapterAnalysis,
            )
            from app.services.personal_analysis_service import PersonalAnalysisService

            user, book, _pbs, runner = await _setup(
                monkeypatch, tmp_path, chapter_fail_titles=("Chapter One",), llm_calls=llm_calls
            )
            async with AsyncSessionLocal() as db:
                task_id = (await PersonalAnalysisService(db).ensure_task(user, book.id)).id
            await runner._run(task_id)

            async with AsyncSessionLocal() as db:
                task = await db.get(PersonalAnalysisTask, task_id)
                assert task.status == "failed"
                rows = (await db.execute(
                    select(PersonalChapterAnalysis)
                    .where(PersonalChapterAnalysis.personal_book_id == book.id)
                )).scalars().all()
                # 第 1 章失败无落库，第 2 章正常落库
                assert [r.chapter_index for r in rows] == [2]

            # 原文与阅读进度不受影响
            async with AsyncSessionLocal() as db:
                from app.services.personal_book_service import PersonalBookService

                pbs = PersonalBookService(db)
                detail = await pbs.get_chapter(user, book.id, 1)
                assert detail.content
                report_404 = False
                try:
                    await PersonalAnalysisService(db).get_report(user, book.id)
                except Exception:
                    report_404 = True
                assert report_404  # 报告未生成

        _run(main())

    def test_report_only_after_chapters_done(self, tmp_path, monkeypatch):
        """全书报告只在所有章节分析完成后生成（进行中查询 404）"""
        llm_calls: list = []

        async def main():
            from app.db.database import AsyncSessionLocal
            from app.services.personal_analysis_service import PersonalAnalysisService

            user, book, _pbs, runner = await _setup(monkeypatch, tmp_path)
            async with AsyncSessionLocal() as db:
                svc = PersonalAnalysisService(db)
                task_id = (await svc.ensure_task(user, book.id)).id
                with pytest.raises(HTTPException):
                    await svc.get_report(user, book.id)  # 未开始：404
            await runner._run(task_id)
            async with AsyncSessionLocal() as db:
                svc = PersonalAnalysisService(db)
                out = await svc.get_report(user, book.id)  # 完成后可读
                assert out.total_word_count > 0

        _run(main())

    def test_no_api_key_falls_back_to_local_analysis(self, tmp_path, monkeypatch):
        """未配置 LLM Key：纯本地分析完成任务，不编造 LLM 结论"""
        llm_calls: list = []

        async def main():
            from sqlalchemy import select

            from app.core.config import get_settings
            from app.db.database import AsyncSessionLocal
            from app.models.personal_analysis import (
                PersonalAnalysisTask, PersonalBookAnalysis,
            )
            from app.services.personal_analysis_service import PersonalAnalysisService

            settings = get_settings()
            monkeypatch.setattr(settings, "DEEPSEEK_API_KEY", "")
            user, book, _pbs, runner = await _setup(monkeypatch, tmp_path, llm_calls=llm_calls)
            async with AsyncSessionLocal() as db:
                task_id = (await PersonalAnalysisService(db).ensure_task(user, book.id)).id
            await runner._run(task_id)

            async with AsyncSessionLocal() as db:
                task = await db.get(PersonalAnalysisTask, task_id)
                assert task.status == "completed"
                report = (await db.execute(
                    select(PersonalBookAnalysis).where(
                        PersonalBookAnalysis.personal_book_id == book.id)
                )).scalars().one()
                assert report.overall_level in ("A1", "A2", "B1", "B2", "C1", "C2")
                assert len(report.reading_recommendations) >= 1
            assert llm_calls == []  # 完全没调 LLM

        _run(main())


# ---------- 辅助 ----------


async def _ok_analyzer(llm_calls):
    """重试阶段用的成功版 fake analyzer"""
    from app.services.personal_analysis_llm import AnalysisLLMClient

    async def fake_analyze_chapter(self, user_id, title, stats, excerpt):
        llm_calls.append(title)
        return {
            "difficulty_level": "B1",
            "difficulty_score": 45.0,
            "grammar_focus": [],
            "chapter_summary": f"{title} 的摘要。",
            "reading_suggestion": "保持原速阅读即可。",
        }, FakeUsage.entry(user_id)

    return fake_analyze_chapter


async def _make_user_in(session_factory):
    from app.models.user import User

    suffix = uuid.uuid4().hex[:10]
    async with session_factory() as db:
        user = User(
            username=f"panb_{suffix}",
            email=f"panb_{suffix}@test.local",
            hashed_password="x",
            email_verified=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user
