"""个人书籍个性化预测（阶段C）：生词预测 + 长难句预测。

设计约束（与阶段B一致）：
- 纯本地计算：只复用 CEFR 词典（cefr_lexicon）与文本统计工具（text_statistics），
  不调用 LLM，不为预测编造任何等级结论
- 按需即时计算，不落库：计算成本低（词典查表 + 正则），且能始终反映
  用户最新等级测试结果与最新生词本，无需缓存失效管理
- 用户隔离：所有接口强制 user_id 归属校验，他人的书与不存在的统一 404
- CPU 密集部分由调用方放入线程池执行（asyncio.to_thread）

预测规则：
- 生词候选：CEFR 等级高于用户水平的词（用户 B1 → B2/C1/C2 词）；
  词典未收录（unknown）且出现 ≥2 次且非纯大写专有名词的词（可能为难词）；
  用户生词本已收藏的词强制命中（用户亲口确认过不认识）
- 长难句候选：超过 LONG_SENTENCE_WORDS(25) 词，或从句标记 ≥2 的句子
"""

import asyncio
import re
from collections import Counter

from fastapi import Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.level_test_result import LevelTestResult
from app.models.personal_book import PersonalBook
from app.models.personal_book_chapter import PersonalBookChapter
from app.models.user import User
from app.models.user_vocabulary import UserVocabulary
from app.schemas.personal_prediction import (
    BookPrediction,
    ChapterPrediction,
    PredictedSentence,
    PredictedWord,
)
from app.services.cefr_lexicon import _LEVEL_RANK, LEVELS, load_lexicon, normalize_token
from app.services.text_statistics import (
    LONG_SENTENCE_WORDS,
    split_sentences,
    tokenize,
)

# 未做过等级测试的用户默认按 B1 处理（中间水平，宁可多提示不少提示）
DEFAULT_LEVEL = "B1"
# 每章生词候选最多返回条数（按 确认生词 > 等级更高 > 词频 排序截断）
MAX_WORDS_PER_CHAPTER = 20
# 每章长难句候选最多返回条数
MAX_SENTENCES_PER_CHAPTER = 5
# unknown 词进入生词候选的最低出现次数（一次性出现的多为专名/噪声）
UNKNOWN_MIN_COUNT = 2
# 从句标记（关系/名词性/状语从句连词粗集合），句内出现 ≥2 个视为长难句候选
_CLAUSE_MARKER_RE = re.compile(
    r"\b(?:which|whom|whose|who|whether|although|though|because|since|unless|until|"
    r"whereas|while|when|before|after|that|if|what|why|how)\b",
    re.IGNORECASE,
)
# 字符偏移定位：按句子前缀在原文中查找的窗口长度
_OFFSET_PROBE_LEN = 40


# ================= 纯计算函数（线程池中执行，不得触碰 DB/ORM） =================


def predict_words(
    text: str,
    user_level: str,
    saved_words: set[str],
    limit: int = MAX_WORDS_PER_CHAPTER,
) -> list[PredictedWord]:
    """生词候选：等级高于用户水平的词 + 高频 unknown 词 + 生词本已收藏词。

    专有名词过滤：只以大写形式出现的词（人名/地名）不作为 unknown 生词。
    """
    lex = load_lexicon()
    user_rank = _LEVEL_RANK[user_level]
    counts: Counter = Counter()
    lower_counts: Counter = Counter()
    for token in tokenize(text):
        word = normalize_token(token)
        if not word:
            continue
        counts[word] += 1
        if token[0].islower():
            lower_counts[word] += 1

    out: list[PredictedWord] = []
    for word, count in counts.items():
        in_vocab = word in saved_words
        level = lex.get(word, "unknown")
        if not in_vocab:
            if level == "unknown":
                # 词典查不到：可能是专业词/生僻词，也可能是专名。
                # 只保留出现多次且有小写形式的词（排除纯大写的专有名词）
                if count < UNKNOWN_MIN_COUNT or lower_counts[word] == 0:
                    continue
            elif _LEVEL_RANK[level] <= user_rank:
                continue  # 用户水平之内的词不提示
        out.append(
            PredictedWord(word=word, level=level, count=count, in_vocabulary=in_vocab)
        )

    # 确认生词（生词本）优先，其次等级更高、词频更高
    out.sort(
        key=lambda w: (
            not w.in_vocabulary,
            -_LEVEL_RANK.get(w.level, -1) if w.level in _LEVEL_RANK else -1,
            -w.count,
        )
    )
    return out[:limit]


def predict_sentences(
    text: str, limit: int = MAX_SENTENCES_PER_CHAPTER
) -> list[PredictedSentence]:
    """长难句候选：超长句（>25 词）或从句标记 ≥2 的句子，按复杂度排序。

    char_start 为句子在章节正文中的字符偏移（近似值：缩写误切等场景下
    可能定位失败，此时为 None，前端可按句子原文检索定位）。
    """
    sentences = split_sentences(text)
    candidates: list[PredictedSentence] = []
    cursor = 0
    for index, sentence in enumerate(sentences, start=1):
        word_count = len(tokenize(sentence))
        markers = len(_CLAUSE_MARKER_RE.findall(sentence))
        if word_count <= LONG_SENTENCE_WORDS and markers < 2:
            continue
        probe = sentence[:_OFFSET_PROBE_LEN]
        char_start: int | None = None
        if probe:
            found = text.find(probe, cursor)
            if found >= 0:
                char_start = found
                cursor = found + 1
        candidates.append(
            PredictedSentence(
                sentence_index=index,
                char_start=char_start,
                word_count=word_count,
                clause_markers=markers,
                text=sentence,
            )
        )
    candidates.sort(key=lambda s: (-(s.word_count + 3 * s.clause_markers), s.sentence_index))
    return candidates[:limit]


# ================= Service（DB 访问 + 编排） =================


class PersonalPredictionService:
    """个性化预测：用户水平获取 + 全书/章节生词与长难句预测"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_owned_book(self, user: User, personal_book_id: int) -> PersonalBook:
        book = (
            await self.db.execute(
                select(PersonalBook).where(
                    PersonalBook.id == personal_book_id,
                    PersonalBook.user_id == user.id,
                )
            )
        ).scalars().first()
        if book is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "个人书籍不存在或无权访问")
        return book

    async def get_user_level(self, user_id: int) -> tuple[str, str]:
        """用户当前英语水平：(等级, 来源)。

        取最新一次等级测试结果；未测试或结果异常时返回默认 B1（source=default）。
        """
        level = (
            await self.db.execute(
                select(LevelTestResult.level)
                .where(LevelTestResult.user_id == user_id)
                .order_by(LevelTestResult.created_at.desc(), LevelTestResult.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if level in LEVELS:
            return level, "test"
        return DEFAULT_LEVEL, "default"

    async def _get_saved_words(self, user_id: int) -> set[str]:
        """用户生词本已收藏的词（归一化小写，跨书）"""
        rows = await self.db.execute(
            select(UserVocabulary.word).where(UserVocabulary.user_id == user_id)
        )
        return {normalize_token(w) for (w,) in rows.all()}

    async def predict_book(self, user: User, personal_book_id: int) -> BookPrediction:
        """全书预测：逐章计算生词与长难句候选"""
        book = await self._get_owned_book(user, personal_book_id)
        level, source = await self.get_user_level(user.id)
        saved = await self._get_saved_words(user.id)

        chapters = (
            await self.db.execute(
                select(PersonalBookChapter)
                .where(PersonalBookChapter.personal_book_id == personal_book_id)
                .order_by(PersonalBookChapter.chapter_index)
            )
        ).scalars().all()
        # 提取纯数据后交给线程池计算（不在线程中触碰 ORM）
        payloads = [(c.chapter_index, c.title, c.content) for c in chapters]
        computed = await asyncio.to_thread(_predict_chapters, payloads, level, saved)
        return BookPrediction(
            personal_book_id=book.id,
            user_level=level,
            level_source=source,
            total_chapters=len(payloads),
            chapters=computed,
        )

    async def predict_chapter(
        self, user: User, personal_book_id: int, chapter_index: int
    ) -> ChapterPrediction:
        """单章预测"""
        await self._get_owned_book(user, personal_book_id)
        level, _source = await self.get_user_level(user.id)
        saved = await self._get_saved_words(user.id)

        chapter = (
            await self.db.execute(
                select(PersonalBookChapter).where(
                    PersonalBookChapter.personal_book_id == personal_book_id,
                    PersonalBookChapter.chapter_index == chapter_index,
                )
            )
        ).scalars().first()
        if chapter is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"第 {chapter_index} 章不存在"
            )
        computed = await asyncio.to_thread(
            _predict_chapters,
            [(chapter.chapter_index, chapter.title, chapter.content)],
            level,
            saved,
        )
        return computed[0]


def _predict_chapters(
    payloads: list[tuple[int, str, str]],
    user_level: str,
    saved_words: set[str],
) -> list[ChapterPrediction]:
    """逐章计算（CPU 密集，调用方需放入线程池）"""
    return [
        ChapterPrediction(
            chapter_index=index,
            title=title,
            words=predict_words(content, user_level, saved_words),
            sentences=predict_sentences(content),
        )
        for index, title, content in payloads
    ]


def get_personal_prediction_service(
    db: AsyncSession = Depends(get_db),
) -> PersonalPredictionService:
    return PersonalPredictionService(db)
