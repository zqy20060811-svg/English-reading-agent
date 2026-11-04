"""生词本 / 书签 / 点词查义业务逻辑单元测试（不依赖数据库与 Redis，用假仓储隔离）。"""

import asyncio
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from app.schemas.study import BookmarkAddRequest, VocabularyAddRequest
from app.services.bookmark_service import BookmarkService
from app.services.lookup_service import _parse_lookup_json, normalize_lookup_word
from app.services.vocabulary_service import VocabularyService, normalize_word

NOW = datetime.now(timezone.utc)  # 模拟数据库 created_at 默认值


# ================= 假仓储 =================

class FakeBook:
    def __init__(self, id, title="书"):
        self.id = id
        self.title = title


class FakeBookRepo:
    def __init__(self, books):
        self.books = {b.id: b for b in books}

    async def get_by_id(self, book_id):
        return self.books.get(book_id)

    async def list_by_ids(self, book_ids):
        return [self.books[i] for i in book_ids if i in self.books]


class FakeVocabRow:
    def __init__(self, id, book_id, word, chapter_index, context_sentence, created_at):
        self.id = id
        self.book_id = book_id
        self.word = word
        self.chapter_index = chapter_index
        self.context_sentence = context_sentence
        self.created_at = created_at


class FakeVocabRepo:
    def __init__(self):
        self.rows: dict[int, FakeVocabRow] = {}
        self.next_id = 1

    async def list_by_user(self, user_id):
        return sorted(self.rows.values(), key=lambda r: -r.id)

    async def get_by_word(self, user_id, word):
        return next((r for r in self.rows.values() if r.word == word), None)

    async def add(self, user_id, book_id, word, chapter_index, context_sentence):
        row = FakeVocabRow(self.next_id, book_id, word, chapter_index, context_sentence, NOW)
        self.next_id += 1
        self.rows[row.id] = row
        return row

    async def remove(self, user_id, word_id):
        return 1 if self.rows.pop(word_id, None) else 0


class FakeBookmarkRow:
    def __init__(self, id, book_id, chapter_index, page_index, excerpt, created_at):
        self.id = id
        self.book_id = book_id
        self.chapter_index = chapter_index
        self.page_index = page_index
        self.excerpt = excerpt
        self.created_at = created_at


class FakeBookmarkRepo:
    def __init__(self):
        self.rows: dict[int, FakeBookmarkRow] = {}
        self.next_id = 1

    async def list_by_user(self, user_id, book_id=None):
        rows = [r for r in self.rows.values() if book_id is None or r.book_id == book_id]
        return sorted(rows, key=lambda r: -r.id)

    async def get_by_position(self, user_id, book_id, chapter_index, page_index):
        return next(
            (r for r in self.rows.values()
             if r.book_id == book_id and r.chapter_index == chapter_index and r.page_index == page_index),
            None,
        )

    async def add(self, user_id, book_id, chapter_index, page_index, excerpt):
        row = FakeBookmarkRow(self.next_id, book_id, chapter_index, page_index, excerpt, NOW)
        self.next_id += 1
        self.rows[row.id] = row
        return row

    async def remove(self, user_id, bookmark_id):
        return 1 if self.rows.pop(bookmark_id, None) else 0


class FakeUser:
    id = 7


def make_vocab_service():
    svc = VocabularyService.__new__(VocabularyService)  # 跳过 __init__，直接注入假依赖
    svc.vocab_repo = FakeVocabRepo()
    svc.book_repo = FakeBookRepo([FakeBook(1, "Alice"), FakeBook(2, "Pride")])
    return svc


def make_bookmark_service():
    svc = BookmarkService.__new__(BookmarkService)
    svc.bookmark_repo = FakeBookmarkRepo()
    svc.book_repo = FakeBookRepo([FakeBook(1, "Alice")])
    return svc


# ================= 生词本 =================

def test_normalize_word_strips_and_lowercases():
    assert normalize_word("  Rabbit ") == "rabbit"


def test_add_word_fills_book_title_and_normalizes():
    svc = make_vocab_service()
    out = asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(
        word="  Wonder ", book_id=1, chapter_index=1, context_sentence="It was a wonder.")))
    assert out.word == "wonder"
    assert out.book_title == "Alice"


def test_add_word_idempotent_same_word():
    svc = make_vocab_service()
    first = asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(word="rabbit", book_id=1)))
    second = asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(word="RABBIT", book_id=2)))
    assert first.id == second.id  # 跨大小写去重，返回同一条
    assert len(svc.vocab_repo.rows) == 1


def test_add_word_rejects_unknown_book():
    svc = make_vocab_service()
    with pytest.raises(HTTPException) as e:
        asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(word="rabbit", book_id=99)))
    assert e.value.status_code == 400


def test_add_word_without_book_id_personal_book():
    """个人书籍收录：不传 book_id，跳过书籍校验，book_title 为空"""
    svc = make_vocab_service()
    out = asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(
        word="  Enterprise ", chapter_index=3, context_sentence="It was an enterprise.")))
    assert out.word == "enterprise"
    assert out.book_id is None
    assert out.book_title == ""
    assert out.chapter_index == 3


def test_add_word_personal_book_idempotent():
    """个人书收录同词幂等，返回已有条目"""
    svc = make_vocab_service()
    first = asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(word="enterprise")))
    second = asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(word="ENTERPRISE", book_id=1)))
    assert first.id == second.id
    assert second.book_id is None  # 返回的是首次收录条目
    assert len(svc.vocab_repo.rows) == 1


def test_list_words_mixed_null_and_public_book_ids():
    """个人书（book_id 为空）与公共书生词混合列表，公共书带书名、个人书书名为空"""
    svc = make_vocab_service()
    asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(word="private", book_id=1)))
    asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(word="personal")))
    rows = asyncio.run(svc.list_words(FakeUser()))
    assert [r.word for r in rows] == ["personal", "private"]  # 倒序：后收录在前
    assert rows[0].book_id is None and rows[0].book_title == ""
    assert rows[1].book_title == "Alice"


def test_remove_word_missing_raises_404():
    svc = make_vocab_service()
    with pytest.raises(HTTPException) as e:
        asyncio.run(svc.remove_word(FakeUser(), 12345))
    assert e.value.status_code == 404


def test_list_words_includes_source_title():
    svc = make_vocab_service()
    asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(word="wonder", book_id=1)))
    asyncio.run(svc.add_word(FakeUser(), VocabularyAddRequest(word="pride", book_id=2)))
    rows = asyncio.run(svc.list_words(FakeUser()))
    assert [r.word for r in rows] == ["pride", "wonder"]  # 倒序：后收录在前
    assert rows[0].book_title == "Pride"


# ================= 书签 =================

def test_add_bookmark_and_idempotent_same_position():
    svc = make_bookmark_service()
    req = BookmarkAddRequest(book_id=1, chapter_index=1, page_index=3, excerpt="The beginning")
    first = asyncio.run(svc.add_bookmark(FakeUser(), req))
    second = asyncio.run(svc.add_bookmark(FakeUser(), req))
    assert first.id == second.id
    assert second.book_title == "Alice"
    assert len(svc.bookmark_repo.rows) == 1


def test_add_bookmark_rejects_unknown_book():
    svc = make_bookmark_service()
    with pytest.raises(HTTPException) as e:
        asyncio.run(svc.add_bookmark(FakeUser(), BookmarkAddRequest(book_id=42, chapter_index=1)))
    assert e.value.status_code == 400


def test_list_bookmarks_filter_by_book():
    svc = make_bookmark_service()
    asyncio.run(svc.add_bookmark(FakeUser(), BookmarkAddRequest(book_id=1, chapter_index=1, page_index=0)))
    rows = asyncio.run(svc.list_bookmarks(FakeUser(), book_id=1))
    assert len(rows) == 1
    assert asyncio.run(svc.list_bookmarks(FakeUser(), book_id=99)) == []


def test_remove_bookmark_missing_raises_404():
    svc = make_bookmark_service()
    with pytest.raises(HTTPException) as e:
        asyncio.run(svc.remove_bookmark(FakeUser(), 12345))
    assert e.value.status_code == 404


# ================= 点词查义 =================

def test_normalize_lookup_word_valid():
    assert normalize_lookup_word(" Don't ") == "don't"
    assert normalize_lookup_word("Well-Known") == "well-known"


def test_normalize_lookup_word_invalid():
    for bad in ["", "1+1", "中文", "word word", "x" * 65]:
        with pytest.raises(HTTPException) as e:
            normalize_lookup_word(bad)
        assert e.value.status_code == 400


def test_parse_lookup_json_plain():
    raw = '{"word": "rabbit", "phonetic": "/ˈræbɪt/", "senses": ["n. 兔子"], ' \
          '"example_en": "A rabbit runs fast.", "example_cn": "兔子跑得很快。"}'
    out = _parse_lookup_json(raw, "rabbit")
    assert out.senses == ["n. 兔子"]
    assert out.phonetic == "/ˈræbɪt/"


def test_parse_lookup_json_with_code_fence():
    raw = '```json\n{"word": "mad", "phonetic": "", "senses": ["adj. 疯狂的"], ' \
          '"example_en": "He is mad.", "example_cn": "他疯了。"}\n```'
    out = _parse_lookup_json(raw, "mad")
    assert out.senses == ["adj. 疯狂的"]


def test_parse_lookup_json_fallback_on_bad_format():
    out = _parse_lookup_json("这不是 JSON", "weird")
    assert out.senses and "不是" in out.senses[0]
