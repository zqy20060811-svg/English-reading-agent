"""端到端验证脚本：真实 EPUB 上传 → 自动分析任务 → 全章分析 → 全书报告。

用法：
    python scripts/e2e_personal_analysis.py <epub路径>

- 真实流程与生产一致：create_book → ensure_task → 后台执行体 _run
- DEEPSEEK_API_KEY 为空时走本地降级模式（无 LLM 调用，Token 为 0）
- 结束后打印任务进度、全书报告、章节样例与 LLM 用量汇总
"""

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.db.database import AsyncSessionLocal, engine  # noqa: E402
from app.models.llm_usage import LLMUsageLog  # noqa: E402
from app.models.personal_analysis import (  # noqa: E402
    PersonalAnalysisTask,
    PersonalBookAnalysis,
    PersonalChapterAnalysis,
)
from app.models.user import User  # noqa: E402
from app.services import personal_analysis_runner as runner  # noqa: E402
from app.services.personal_analysis_service import PersonalAnalysisService  # noqa: E402
from app.services.personal_book_service import PersonalBookService  # noqa: E402


async def main(book_path: str) -> None:
    await engine.dispose()
    data = Path(book_path).read_bytes()

    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:8]
        user = User(
            username=f"e2e_{suffix}",
            email=f"e2e_{suffix}@test.local",
            hashed_password="x",
            email_verified=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        book, dup = await PersonalBookService(db).create_book(
            user, Path(book_path).name, data
        )
        print(f"[1] 上传成功：《{book.title}》 / {book.author} / {book.chapter_count} 章 / {book.word_count} 词（重复命中：{dup}）")

        task = await PersonalAnalysisService(db).ensure_task(user, book.id)
        task_id = task.id
        print(f"[2] 分析任务已创建：#{task_id}（status={task.status}）")

    t0 = time.monotonic()
    await runner._run(task_id)
    elapsed = time.monotonic() - t0

    async with AsyncSessionLocal() as db:
        task = await db.get(PersonalAnalysisTask, task_id)
        print(f"[3] 任务结束：status={task.status} 完成 {task.completed_chapters}/{task.total_chapters} "
              f"失败 {task.failed_chapters} 耗时 {elapsed:.1f}s")
        if task.error_message:
            print(f"    error: {task.error_message[:200]}")

        report = (await db.execute(
            select(PersonalBookAnalysis).where(
                PersonalBookAnalysis.personal_book_id == book.id)
        )).scalars().first()
        if report:
            print(f"[4] 全书报告：等级 {report.overall_level} / 分数 {report.difficulty_score} / "
                  f"总词数 {report.total_word_count}")
            print(f"    章节难度分布：{report.chapter_difficulty_distribution}")
            print(f"    词汇分布：{report.vocabulary_level_distribution}")
            print(f"    语法特征：{list(report.main_grammar_features.items())[:4]}")
            print(f"    阅读建议：")
            for r in report.reading_recommendations:
                print(f"      - {r}")

        sample = (await db.execute(
            select(PersonalChapterAnalysis).where(
                PersonalChapterAnalysis.personal_book_id == book.id,
                PersonalChapterAnalysis.chapter_index == 1)
        )).scalars().first()
        if sample:
            print(f"[5] 第 1 章样例：难度 {sample.difficulty_level}（{sample.difficulty_score}） "
                  f"{sample.word_count} 词 / 平均句长 {sample.average_sentence_length} / "
                  f"长句比 {sample.long_sentence_ratio}")
            print(f"    摘要：{sample.chapter_summary[:120]}")

        rows = (await db.execute(
            select(
                LLMUsageLog.scene,
                func.count().label("calls"),
                func.sum(LLMUsageLog.prompt_tokens).label("pt"),
                func.sum(LLMUsageLog.completion_tokens).label("ct"),
                func.sum(LLMUsageLog.duration_ms).label("ms"),
            ).where(LLMUsageLog.user_id == user.id).group_by(LLMUsageLog.scene)
        )).all()
        print(f"[6] LLM 用量（scene / 调用次数 / 输入 token / 输出 token / 累计耗时）：")
        for scene, calls, pt, ct, ms in rows:
            print(f"      {scene} / {calls} / {pt} / {ct} / {ms}ms")
        if not rows:
            print("      （无 LLM 调用：本地降级模式或任务失败）")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1]))
