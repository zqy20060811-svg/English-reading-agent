"""个人书籍个性化预测（阶段C）测试。

- TestPredictWords / TestPredictSentences：纯计算单元测试（注入词典，不依赖 data/cefr）
- TestPersonalPredictionDB：服务层集成测试（需要 PostgreSQL）

运行：python -m pytest tests/test_personal_prediction.py -v
"""

import asyncio
import io
import uuid
import zipfile

import pytest
from fastapi import HTTPException

from app.services import personal_prediction_service as pps
from app.services.personal_prediction_service import (
    PersonalPredictionService,
    predict_sentences,
    predict_words,
)

# 供单元测试注入的确定性行词典
_FAKE_LEX = {
    "cat": "A1",
    "journey": "B1",
    "remarkable": "B2",
    "gossamer": "C1",
    "ephemeral": "C2",
}


# ================= 生词预测（纯单元） =================


class TestPredictWords:
    def test_words_above_user_level_selected(self, monkeypatch):
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))
        text = "The cat took a journey. It was remarkable, gossamer and ephemeral."
        words = {w.word for w in predict_words(text, "B1", set())}
        # B1 用户：B1 及以下的 cat/journey 不提示，B2/C1/C2 提示
        assert "remarkable" in words
        assert "gossamer" in words
        assert "ephemeral" in words
        assert "cat" not in words
        assert "journey" not in words

    def test_level_gap_narrows_with_higher_user(self, monkeypatch):
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))
        text = "The remarkable gossamer ephemeral story."
        words = {w.word for w in predict_words(text, "C1", set())}
        assert words == {"ephemeral"}  # C1 用户只提示 C2；B2/C1 词不再提示

    def test_proper_noun_excluded(self, monkeypatch):
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))
        # Elizabeth 只以大写出现 → 专有名词，不进 unknown 候选
        text = "Elizabeth met him. Elizabeth smiled. Elizabeth left quietly."
        words = {w.word for w in predict_words(text, "B1", set())}
        assert "elizabeth" not in words

    def test_unknown_word_needs_frequency_and_lowercase(self, monkeypatch):
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))
        text = (
            "The quizzle was strange. The quizzle returned. "
            "A blorp appeared once."
        )
        by_word = {w.word: w for w in predict_words(text, "B1", set())}
        assert "quizzle" in by_word          # 出现 2 次的小写 unknown 词 → 候选
        assert by_word["quizzle"].level == "unknown"
        assert "blorp" not in by_word        # 只出现 1 次 → 噪声，不提示

    def test_saved_word_forced_in(self, monkeypatch):
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))
        text = "The cat slept."
        words = {w.word: w for w in predict_words(text, "B1", {"cat"})}
        assert words["cat"].in_vocabulary is True  # 生词本确认过的词强制命中

    def test_limit_and_sorting(self, monkeypatch):
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))
        text = " ".join(["gossamer"] * 5 + ["ephemeral"] * 3 + ["remarkable"] * 2)
        out = predict_words(text, "A1", set(), limit=2)
        assert len(out) == 2
        assert out[0].word == "ephemeral"  # 等级更高者优先
        assert out[1].word == "gossamer"


# ================= 长难句预测（纯单元） =================


class TestPredictSentences:
    def test_long_and_clause_sentences_selected(self):
        text = (
            "He ran. "
            "The old man who had lived by the sea for many years told the "
            "children a story about the ship that sailed beyond the horizon "
            "and never came back. "
            "She slept."
        )
        out = predict_sentences(text)
        assert len(out) == 1
        s = out[0]
        assert s.sentence_index == 2       # 第 2 句
        assert s.word_count > 25
        assert s.char_start is not None    # 能在原文中定位
        assert s.clause_markers >= 2
        assert text[s.char_start:].startswith("The old man")

    def test_short_sentences_all_filtered(self):
        out = predict_sentences("I like cats. She reads books every single night.")
        assert out == []

    def test_limit_keeps_most_complex(self):
        parts = ["word " * 30 + "here."] + ["fine here."] * 5
        out = predict_sentences(" ".join(parts), limit=1)
        assert len(out) == 1
        assert out[0].sentence_index == 1


# ================= 服务层集成（需要 PostgreSQL） =================

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
    not _db_available(), reason="PostgreSQL 不可用，跳过个人书预测数据库测试"
)


def _run(coro):
    async def _wrap():
        from app.db.database import engine

        await engine.dispose()
        await coro

    return asyncio.run(_wrap())


_LONG_SENTENCE = (
    "The old man who had lived by the sea for many years told the children "
    "a story about the ship that sailed beyond the horizon and never came back."
)
_CH1 = (
    "<html><body><h1>Chapter One</h1>"
    "<p>The cat took a quiet journey through the garden. Elizabeth watched. "
    "The quizzle was strange, and the quizzle returned. " + _LONG_SENTENCE + "</p>"
    "</body></html>"
)
_CH2 = "<html><body><h2>Chapter Two</h2><p>Gossamer wings drifted, ephemeral and bright.</p></body></html>"

_CONTAINER = """<?xml version="1.0"?>
<container xmlns="urn:oasis:names:tc:opendocument:xmlns:container" version="1.0">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

_OPF = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>Prediction Test Book</dc:title>
    <dc:creator>Test Author</dc:creator>
    <dc:language>en</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="ch1.xhtml" media-type="application/xhtml+xml"/>
    <item id="c2" href="ch2.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/><itemref idref="c2"/></spine>
</package>"""


def _build_epub() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/container.xml", _CONTAINER)
        zf.writestr("OEBPS/content.opf", _OPF)
        zf.writestr("OEBPS/ch1.xhtml", _CH1)
        zf.writestr("OEBPS/ch2.xhtml", _CH2)
    return buf.getvalue()


async def _make_user(db):
    from app.models.user import User

    suffix = uuid.uuid4().hex[:10]
    user = User(
        username=f"ppd_{suffix}",
        email=f"ppd_{suffix}@example.com",
        hashed_password="x",
        email_verified=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def _make_book(user) -> "object":
    from app.db.database import AsyncSessionLocal
    from app.services.personal_book_service import PersonalBookService

    async with AsyncSessionLocal() as db:
        service = PersonalBookService(db)
        book, _ = await service.create_book(user, "pred.epub", _build_epub())
        return book


async def _add_level_result(user_id: int, level: str):
    from app.db.database import AsyncSessionLocal
    from app.models.level_test_result import LevelTestResult

    async with AsyncSessionLocal() as db:
        db.add(
            LevelTestResult(
                user_id=user_id,
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


@requires_db
class TestPersonalPredictionDB:
    def test_untested_user_default_level_and_word_selection(self, monkeypatch):
        """未测试用户：默认 B1（source=default）；高于水平的词入选，水平内不提示"""
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))

        async def main():
            from app.db.database import AsyncSessionLocal

            user = None
            async with AsyncSessionLocal() as db:
                user = await _make_user(db)
            book = await _make_book(user)

            async with AsyncSessionLocal() as db:
                out = await PersonalPredictionService(db).predict_book(user, book.id)
                assert out.user_level == "B1"
                assert out.level_source == "default"
                assert out.total_chapters == 2
                assert [c.chapter_index for c in out.chapters] == [1, 2]

                ch1 = out.chapters[0]
                words = {w.word for w in ch1.words}
                # 预测测试书里没有 B2+ 词 → ch1 无候选（cat/journey 在 B1 水平内）
                assert "cat" not in words
                assert "journey" not in words
                # unknown 高频词（quizzle x2）入选，专有名词 Elizabeth 不入选
                assert "quizzle" in words
                assert "elizabeth" not in words
                # 长难句候选：第 1 章有长句，第 2 章没有
                assert len(ch1.sentences) == 1
                assert ch1.sentences[0].word_count > 25
                assert out.chapters[1].sentences == []
                # 第 2 章的 gossamer/ephemeral（C1/C2）对 B1 用户是生词候选
                ch2_words = {w.word for w in out.chapters[1].words}
                assert "gossamer" in ch2_words and "ephemeral" in ch2_words

        _run(main())

    def test_latest_level_test_result_wins(self, monkeypatch):
        """有等级测试：取最新一次结果（B1）而非更早的（A2）"""
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))

        async def main():
            from sqlalchemy import func, select

            from app.db.database import AsyncSessionLocal
            from app.models.level_test_result import LevelTestResult

            async with AsyncSessionLocal() as db:
                user = await _make_user(db)
            book = await _make_book(user)
            await _add_level_result(user.id, "A2")
            await _add_level_result(user.id, "B1")  # 更新的一次

            async with AsyncSessionLocal() as db:
                out = await PersonalPredictionService(db).predict_book(user, book.id)
                assert out.user_level == "B1"
                assert out.level_source == "test"
                ch1_words = {w.word for w in out.chapters[0].words}
                # journey 是 B1：对最新水平 B1 不再是生词
                assert "journey" not in ch1_words

            count = 0
            async with AsyncSessionLocal() as db:
                count = (
                    await db.execute(
                        select(func.count()).select_from(LevelTestResult).where(
                            LevelTestResult.user_id == user.id
                        )
                    )
                ).scalar()
            assert count == 2

        _run(main())

    def test_level_downgrade_changes_prediction(self, monkeypatch):
        """水平更低（A2）的用户：B1 词 journey 也成为生词候选"""
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))

        async def main():
            from app.db.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                user = await _make_user(db)
            book = await _make_book(user)
            await _add_level_result(user.id, "A2")

            async with AsyncSessionLocal() as db:
                svc = PersonalPredictionService(db)
                out = await svc.predict_book(user, book.id)
                assert out.user_level == "A2"
                ch1_words = {w.word: w for w in out.chapters[0].words}
                assert ch1_words["journey"].level == "B1"
                # A2 用户的水位内词只有 cat，其余候选都应来自更高等级或 unknown
                assert all(
                    w.level in ("B1", "B2", "C1", "C2", "unknown")
                    for w in out.chapters[0].words
                )

        _run(main())

    def test_saved_vocabulary_word_forced_in(self, monkeypatch):
        """生词本收藏词：即使等级在用户水平内也强制命中（in_vocabulary=True）"""
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))

        async def main():
            from app.db.database import AsyncSessionLocal
            from app.models.book import Book
            from app.models.user_vocabulary import UserVocabulary

            async with AsyncSessionLocal() as db:
                user = await _make_user(db)
                # UserVocabulary.book_id 外键指向公共 books 表，构造最小公共书行
                suffix = uuid.uuid4().hex[:8]
                public_book = Book(
                    gutenberg_id=int(suffix[:6], 16) % 1_000_000 + 10_000_000,
                    title="Public Book",
                    author="A",
                    year=1900,
                    genre="fiction",
                    synopsis="s",
                    source_url="https://example.com/book",
                )
                db.add(public_book)
                await db.flush()
                db.add(
                    UserVocabulary(
                        user_id=user.id, book_id=public_book.id, word="cat"
                    )
                )
                await db.commit()
            book = await _make_book(user)

            async with AsyncSessionLocal() as db:
                out = await PersonalPredictionService(db).predict_book(user, book.id)
                ch1 = {w.word: w for w in out.chapters[0].words}
                assert ch1["cat"].in_vocabulary is True

            # 单章接口同样生效
            async with AsyncSessionLocal() as db:
                chap = await PersonalPredictionService(db).predict_chapter(
                    user, book.id, 1
                )
                words = {w.word: w for w in chap.words}
                assert words["cat"].in_vocabulary is True

        _run(main())

    def test_user_isolation_and_missing_chapter(self, monkeypatch):
        """用户 B 无法读取用户 A 的预测（404）；不存在的章节 404"""
        monkeypatch.setattr(pps, "load_lexicon", lambda: dict(_FAKE_LEX))

        async def main():
            from app.db.database import AsyncSessionLocal

            async with AsyncSessionLocal() as db:
                user_a = await _make_user(db)
                user_b = await _make_user(db)
            book = await _make_book(user_a)

            async with AsyncSessionLocal() as db:
                svc = PersonalPredictionService(db)
                # A 自己可用
                out = await svc.predict_book(user_a, book.id)
                assert out.personal_book_id == book.id
                chap = await svc.predict_chapter(user_a, book.id, 1)
                assert chap.chapter_index == 1
                # B 访问 A 的书 → 404
                with pytest.raises(HTTPException) as exc:
                    await svc.predict_book(user_b, book.id)
                assert exc.value.status_code == 404
                with pytest.raises(HTTPException) as exc:
                    await svc.predict_chapter(user_b, book.id, 1)
                assert exc.value.status_code == 404
                # A 访问不存在的章节 → 404
                with pytest.raises(HTTPException):
                    await svc.predict_chapter(user_a, book.id, 99)

        _run(main())
