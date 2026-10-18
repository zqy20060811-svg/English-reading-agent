"""英语水平测试评分与定级逻辑单元测试（不依赖数据库，用假 Repository 隔离）。"""

import asyncio

import pytest

from app.level_bank import LEVEL_BANK, LEVELS, LEVEL_SCORE, DIMENSIONS, questions_by_id
from app.repositories.level_test_repository import BookDifficultyRow
from app.schemas.level_test import AnswerItem, LevelTestSubmit
from app.services.level_test_service import (
    READING_DIFFICULTY_LIMIT,
    LevelTestService,
)


class FakeRepo:
    """假数据层：记录保存的行，返回固定的书目难度数据"""

    def __init__(self, books):
        self.books = books
        self.saved = []

    async def save(self, row):
        row.id = len(self.saved) + 1
        self.saved.append(row)
        return row

    async def get_latest(self, user_id):
        return self.saved[-1] if self.saved else None

    async def books_by_difficulty(self):
        return self.books


FAKE_BOOKS = [
    BookDifficultyRow(1, "Easy Book", "A", 1000.0),
    BookDifficultyRow(2, "Mid Book", "B", 2000.0),
    BookDifficultyRow(3, "Hard Book", "C", 5000.0),
]


def make_service() -> LevelTestService:
    return LevelTestService(FakeRepo(FAKE_BOOKS))


def make_submit(choice_map: dict[str, int]) -> LevelTestSubmit:
    """按 {题目id: 选项下标} 构造整卷提交；未指定的题目用正确答案补齐"""
    bank = questions_by_id()
    answers = [
        AnswerItem(question_id=q.id, choice=choice_map.get(q.id, q.answer_index))
        for q in LEVEL_BANK
    ]
    return LevelTestSubmit(answers=answers)


# ---------- 题库结构 ----------


def test_bank_structure_and_answer_distribution():
    assert len(LEVEL_BANK) == 24
    # 等级 × 维度全覆盖，每格 2 题
    combos = {(q.level, q.dimension) for q in LEVEL_BANK}
    assert len(combos) == len(LEVELS) * len(DIMENSIONS)
    # 正确答案不在同一位置（防"全选 A"得分）
    positions = {q.answer_index for q in LEVEL_BANK}
    assert len(positions) == 4
    for q in LEVEL_BANK:
        assert 0 <= q.answer_index < len(q.options)


# ---------- 定级规则 ----------


def _by_level(correct_counts: dict[str, int]) -> dict[str, dict]:
    """构造各等级统计（每等级 6 题）"""
    return {
        lv: {"correct": correct_counts.get(lv, 0), "total": 6} for lv in LEVELS
    }


def test_estimate_level_all_correct():
    level, _ = LevelTestService._estimate_level(_by_level({"A2": 6, "B1": 6, "B2": 6, "C1": 6}))
    assert level == "C1"


def test_estimate_level_all_wrong():
    level, _ = LevelTestService._estimate_level(_by_level({}))
    assert level == "A1"


def test_estimate_level_partial():
    # A2、B1 达标，B2/C1 不达标 -> B1
    level, _ = LevelTestService._estimate_level(_by_level({"A2": 6, "B1": 4}))
    assert level == "B1"
    # 仅 A2 达标 -> A2
    level, _ = LevelTestService._estimate_level(_by_level({"A2": 3}))
    assert level == "A2"


def test_estimate_level_exact_50_percent_boundary():
    # 正好 50% 视为达标（3/6）
    level, _ = LevelTestService._estimate_level(_by_level({"A2": 3, "B1": 3, "B2": 3, "C1": 3}))
    assert level == "C1"


def test_estimate_level_c1_fail_does_not_certify_b2():
    # 回归：C1 失败时不得把同样失败的 B2 认定为达标
    level, _ = LevelTestService._estimate_level(_by_level({"A2": 6, "B1": 6}))
    assert level == "B1"
    level, _ = LevelTestService._estimate_level(_by_level({"A2": 6, "B1": 0}))
    assert level == "A2"


# ---------- 提交校验 ----------


def test_submit_rejects_unknown_question_id():
    service = make_service()
    data = LevelTestSubmit(answers=[AnswerItem(question_id="no-such-id", choice=0)])
    with pytest.raises(ValueError, match="未知题目"):
        asyncio.run(service.submit(user_id=1, data=data))


def test_submit_rejects_duplicate_answers():
    service = make_service()
    data = LevelTestSubmit(
        answers=[
            AnswerItem(question_id=LEVEL_BANK[0].id, choice=0),
            AnswerItem(question_id=LEVEL_BANK[0].id, choice=1),
        ]
    )
    with pytest.raises(ValueError, match="重复作答"):
        asyncio.run(service.submit(user_id=1, data=data))


def test_submit_rejects_missing_answers():
    service = make_service()
    bank = questions_by_id()
    # 只答第一题，漏掉其余 23 题
    data = LevelTestSubmit(answers=[AnswerItem(question_id=LEVEL_BANK[0].id, choice=0)])
    with pytest.raises(ValueError, match="未作答"):
        asyncio.run(service.submit(user_id=1, data=data))
    assert bank  # 保持 bank 引用被使用


# ---------- 评分与保存 ----------


def test_submit_all_correct_scores_and_saves():
    service = make_service()
    result = asyncio.run(service.submit(user_id=7, data=make_submit({})))
    assert result.total_score == 60 and result.max_score == 60
    assert result.level == "C1" and result.recommended_level == "C1"
    assert result.vocabulary_acc == result.grammar_acc == result.reading_acc == 1.0
    # 已落库且详情完整
    assert len(service.repo.saved) == 1
    row = service.repo.saved[0]
    assert row.user_id == 7 and row.details["wrong_ids"] == []


def test_submit_all_wrong_gets_min_score():
    service = make_service()
    # 每题都选正确答案的下一个位置 -> 全错
    wrong_map = {q.id: (q.answer_index + 1) % 4 for q in LEVEL_BANK}
    result = asyncio.run(service.submit(user_id=7, data=make_submit(wrong_map)))
    assert result.total_score == 0
    assert result.level == "A1" and result.recommended_level == "A1"
    assert len(service.repo.saved[0].details["wrong_ids"]) == 24


def test_submit_a2_only_pass_reaches_a2():
    service = make_service()
    # A2 全对、B1 及以上全错 -> 定级 A2
    choice_map = {
        q.id: (q.answer_index if q.level == "A2" else (q.answer_index + 1) % 4)
        for q in LEVEL_BANK
    }
    result = asyncio.run(service.submit(user_id=7, data=make_submit(choice_map)))
    assert result.level == "A2"
    assert result.total_score == 6  # 6 题 × 1 分


# ---------- 书目推荐 ----------


def test_recommend_books_comes_from_repo_data():
    service = make_service()
    result = asyncio.run(service.submit(user_id=7, data=make_submit({})))
    # C1 上限 6000：Easy/Mid/Hard 均在限内，取最接近上限的 3 本
    assert [r.title for r in result.recommendations] == ["Easy Book", "Mid Book", "Hard Book"]


def test_recommend_books_falls_back_to_easiest_when_no_match():
    # 全部书目都超出 A1 上限 -> 退化为全库最易的 3 本
    books = [
        BookDifficultyRow(1, "Book1", "A", 1500.0),
        BookDifficultyRow(2, "Book2", "B", 1600.0),
        BookDifficultyRow(3, "Book3", "C", 1700.0),
        BookDifficultyRow(4, "Book4", "D", 9999.0),
    ]
    service = LevelTestService(FakeRepo(books))
    result = asyncio.run(service.submit(user_id=7, data=make_submit({q.id: (q.answer_index + 1) % 4 for q in LEVEL_BANK})))
    assert result.level == "A1"
    assert [r.title for r in result.recommendations] == ["Book1", "Book2", "Book3"]


def test_reading_difficulty_limit_covers_all_levels():
    for lv in ["A1"] + LEVELS:
        assert lv in READING_DIFFICULTY_LIMIT
