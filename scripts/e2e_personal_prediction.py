"""端到端验证脚本（阶段C）：真实 EPUB → 用户等级 → 个性化生词/长难句预测。

用法：
    python scripts/e2e_personal_prediction.py <epub路径> [用户等级]

- 预测为纯本地计算（CEFR 词典 + 规则），不调 LLM
- 用户等级默认 B1；传入如 A2/B2 可对比不同水平下的预测差异
- 结束后打印每章生词候选与长难句候选样例、全书汇总与耗时
"""

import asyncio
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.database import AsyncSessionLocal, engine  # noqa: E402
from app.models.level_test_result import LevelTestResult  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.cefr_lexicon import CITATION, load_lexicon  # noqa: E402
from app.services.personal_book_service import PersonalBookService  # noqa: E402
from app.services.personal_prediction_service import (  # noqa: E402
    PersonalPredictionService,
)


async def main(book_path: str, level: str) -> None:
    await engine.dispose()
    data = Path(book_path).read_bytes()
    lex_size = len(load_lexicon())
    print(f"[0] CEFR 词典规模：{lex_size} 词（{CITATION}）")

    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:8]
        user = User(
            username=f"e2ep_{suffix}",
            email=f"e2ep_{suffix}@example.com",
            hashed_password="x",
            email_verified=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)

        db.add(
            LevelTestResult(
                user_id=user.id,
                total_score=10,
                max_score=20,
                level=level,
                vocabulary_acc=0.5,
                grammar_acc=0.5,
                reading_acc=0.5,
                recommended_level=level,
                details={},
            )
        )
        await db.commit()

        book, dup = await PersonalBookService(db).create_book(
            user, Path(book_path).name, data
        )
        print(f"[1] 上传成功：《{book.title}》 / {book.author} / {book.chapter_count} 章（重复命中：{dup}）")
        print(f"[2] 用户水平：{level}（等级测试结果）")

    t0 = time.monotonic()
    async with AsyncSessionLocal() as db:
        prediction = await PersonalPredictionService(db).predict_book(user, book.id)
    elapsed = time.monotonic() - t0

    total_words = 0
    total_sentences = 0
    print(f"[3] 预测完成：level_source={prediction.level_source}，耗时 {elapsed:.2f}s")
    for ch in prediction.chapters:
        total_words += len(ch.words)
        total_sentences += len(ch.sentences)
        if ch.chapter_index > 3:
            continue
        print(f"\n---- 第 {ch.chapter_index} 章《{ch.title}》 生词候选 {len(ch.words)} 个 ----")
        for w in ch.words[:10]:
            flag = " [生词本]" if w.in_vocabulary else ""
            print(f"    {w.word:<20} {w.level:<8} 出现 {w.count} 次{flag}")
        print(f"---- 长难句候选 {len(ch.sentences)} 句 ----")
        for s in ch.sentences[:2]:
            pos = f"偏移 {s.char_start}" if s.char_start is not None else "未定位"
            print(f"    第{s.sentence_index}句（{s.word_count} 词 / 从句标记 {s.clause_markers} / {pos}）")
            print(f"      {s.text[:150]}{'...' if len(s.text) > 150 else ''}")

    print(f"\n[4] 全书汇总：生词候选 {total_words} 个，长难句候选 {total_sentences} 句（每章上限 生词20/长句5）")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "B1"))
