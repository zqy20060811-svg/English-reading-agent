"""英语水平测试业务逻辑：评分 → 定级 → 能力分析 → 保存 → 按难度推荐书目。

链路：GET 题目（预设题库，不含答案）→ 用户提交 → 自动评分 → CEFR 定级 →
结果落库（保留历史）→ 返回等级、各维度分析与匹配难度的书目推荐。
"""

import math

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.level_bank import DIMENSIONS, LEVEL_BANK, LEVEL_SCORE, LEVELS, LevelQuestion, questions_by_id
from app.models.level_test_result import LevelTestResult
from app.repositories.level_test_repository import LevelTestRepository
from app.schemas.level_test import (
    BookRecommendation,
    LevelTestPaperOut,
    LevelTestResultOut,
    LevelTestSubmit,
    LevelQuestionOut,
)

# 推荐阅读难度门槛：评估等级 -> 该等级读者适合的平均章节词数上限（books 表按
# book_chapters 平均章节词数衡量难度）。A1 为入门（尚不适合独立阅读长文）
READING_DIFFICULTY_LIMIT = {"A1": 1000, "A2": 1800, "B1": 2800, "B2": 4200, "C1": 6000}

# 各能力维度的中文描述（用于能力分析文案）
DIMENSION_DESCRIPTIONS = {
    "vocabulary": "词汇：",
    "grammar": "语法：",
    "reading": "阅读理解：",
}


class LevelTestService:
    """英语水平测试服务"""

    def __init__(self, repo: LevelTestRepository):
        self.repo = repo

    # ---------- 题目下发 ----------

    @staticmethod
    def get_paper() -> LevelTestPaperOut:
        return LevelTestPaperOut(
            total_questions=len(LEVEL_BANK),
            max_score=sum(LEVEL_SCORE[q.level] for q in LEVEL_BANK),
            questions=[
                LevelQuestionOut(
                    id=q.id, level=q.level, dimension=q.dimension, text=q.text, options=q.options
                )
                for q in LEVEL_BANK
            ],
        )

    # ---------- 提交与评分 ----------

    async def submit(self, user_id: int, data: LevelTestSubmit) -> LevelTestResultOut:
        bank = questions_by_id()

        # 校验：题目 id 必须全部合法且不重复（保证评分标准可控）
        seen: set[str] = set()
        for item in data.answers:
            if item.question_id not in bank:
                raise ValueError(f"未知题目 id：{item.question_id}")
            if item.question_id in seen:
                raise ValueError(f"题目重复作答：{item.question_id}")
            seen.add(item.question_id)
        unanswered = set(bank) - seen
        if unanswered:
            raise ValueError(f"有 {len(unanswered)} 题未作答（例如 {sorted(unanswered)[0]}）")

        by_level = {lv: {"correct": 0, "total": 0} for lv in LEVELS}
        by_dim = {d: {"correct": 0, "total": 0} for d in DIMENSIONS}
        wrong_ids: list[str] = []
        total_score = 0

        for item in data.answers:
            q: LevelQuestion = bank[item.question_id]
            ok = item.choice == q.answer_index
            by_level[q.level]["total"] += 1
            by_dim[q.dimension]["total"] += 1
            if ok:
                by_level[q.level]["correct"] += 1
                by_dim[q.dimension]["correct"] += 1
                total_score += LEVEL_SCORE[q.level]
            else:
                wrong_ids.append(q.id)

        level, level_detail = self._estimate_level(by_level)
        dim_acc = {d: by_dim[d]["correct"] / by_dim[d]["total"] for d in DIMENSIONS}
        recommended_level = self._recommend_level(level)

        row = LevelTestResult(
            user_id=user_id,
            total_score=total_score,
            max_score=self.get_paper().max_score,
            level=level,
            vocabulary_acc=dim_acc["vocabulary"],
            grammar_acc=dim_acc["grammar"],
            reading_acc=dim_acc["reading"],
            recommended_level=recommended_level,
            details={"by_level": level_detail, "by_dim": by_dim, "wrong_ids": wrong_ids},
        )
        row = await self.repo.save(row)
        recommendations = await self._recommend_books(self.repo, recommended_level)
        return self._to_out(row, recommendations)

    # ---------- 历史结果查询 ----------

    async def get_latest_result(self, user_id: int) -> LevelTestResultOut | None:
        row = await self.repo.get_latest(user_id)
        if row is None:
            return None
        recommendations = await self._recommend_books(self.repo, row.recommended_level)
        return self._to_out(row, recommendations)

    # ---------- 内部逻辑 ----------

    @staticmethod
    def _estimate_level(by_level: dict[str, dict]) -> tuple[str, dict[str, str]]:
        """定级规则（可解释）：从 C1 往下找第一个正确率 >= 50% 的等级作为评估等级；
        若 A2 也不达标则为 A1（入门）。
        返回 (等级, 各等级得分明细文字)。"""
        detail = {
            lv: f"{v['correct']}/{v['total']}（{LEVEL_SCORE[lv]}分/题）" for lv, v in by_level.items()
        }
        for i in range(len(LEVELS) - 1, -1, -1):
            stat = by_level[LEVELS[i]]
            if stat["correct"] / stat["total"] >= 0.5:
                return LEVELS[i], detail
        return "A1", detail

    @staticmethod
    def _recommend_level(level: str) -> str:
        """推荐阅读难度：与评估等级一致（题库定级偏严格，同档书目更稳妥）"""
        return level

    @staticmethod
    def _analysis_texts(dim_acc: dict[str, float], level: str) -> dict[str, str]:
        def text(dim: str) -> str:
            acc = dim_acc[dim]
            if acc >= 0.9:
                grade = "优秀"
            elif acc >= 0.75:
                grade = "良好"
            elif acc >= 0.5:
                grade = "一般，建议针对性练习"
            else:
                grade = "薄弱，建议从该维度低等级材料补起"
            return f"{DIMENSION_DESCRIPTIONS[dim]}正确率 {acc:.0%}：{grade}"

        return {d: text(d) for d in DIMENSIONS} | {"overall": f"当前水平评估为 {level}"}

    @staticmethod
    async def _recommend_books(
        repo: LevelTestRepository, recommended_level: str, limit: int = 3
    ) -> list[BookRecommendation]:
        """按平均章节词数（难度代理指标）匹配推荐书目。

        先取难度上限内词数最接近上限的 limit 本；若无匹配（如入门 A1 全库都
        超纲），退化为全库最容易的 limit 本。
        """
        max_words = READING_DIFFICULTY_LIMIT.get(recommended_level, 1800)
        all_books = await repo.books_by_difficulty()
        with_chapters = [b for b in all_books if math.isfinite(b.avg_chapter_words)]
        matched = [b for b in with_chapters if b.avg_chapter_words <= max_words]
        picked = (matched[-limit:] if len(matched) > limit else matched) or with_chapters[:limit]
        return [
            BookRecommendation(
                book_id=b.book_id,
                title=b.title,
                author=b.author,
                avg_chapter_words=b.avg_chapter_words,
            )
            for b in picked
        ]

    @staticmethod
    def _to_out(row: LevelTestResult, recommendations: list[BookRecommendation]) -> LevelTestResultOut:
        dim_acc = {
            "vocabulary": row.vocabulary_acc,
            "grammar": row.grammar_acc,
            "reading": row.reading_acc,
        }
        return LevelTestResultOut(
            total_score=row.total_score,
            max_score=row.max_score,
            level=row.level,
            vocabulary_acc=row.vocabulary_acc,
            grammar_acc=row.grammar_acc,
            reading_acc=row.reading_acc,
            analysis=LevelTestService._analysis_texts(dim_acc, row.level),
            level_detail=row.details["by_level"],
            recommended_level=row.recommended_level,
            recommendations=recommendations,
            created_at=row.created_at,
        )


def get_level_test_service(db: AsyncSession = Depends(get_db)) -> LevelTestService:
    """FastAPI 依赖注入：构建带数据访问层的测试服务"""
    return LevelTestService(LevelTestRepository(db))
