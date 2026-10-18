from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

DIMENSION_DESCRIPTIONS = {
    "vocabulary": "词汇",
    "grammar": "语法",
    "reading": "阅读理解",
}


class LevelQuestionOut(BaseModel):
    """下发的测试题（不含答案与解析）"""

    id: str
    level: str
    dimension: str
    text: str
    options: list[str]


class LevelTestPaperOut(BaseModel):
    """整卷：预设题库全部题目"""

    total_questions: int
    max_score: int
    questions: list[LevelQuestionOut]


class AnswerItem(BaseModel):
    """单题作答"""

    question_id: str
    choice: int = Field(ge=0, le=3, description="选项下标 0~3")


class LevelTestSubmit(BaseModel):
    """提交整卷答案"""

    answers: list[AnswerItem] = Field(min_length=1, max_length=100)


class BookRecommendation(BaseModel):
    """按难度匹配的推荐书目"""

    book_id: int
    title: str
    author: str
    avg_chapter_words: float


class LevelTestResultOut(BaseModel):
    """测试结果：等级 + 能力分析 + 推荐阅读难度"""

    model_config = ConfigDict(from_attributes=True)

    total_score: int
    max_score: int
    level: str                                    # 评估等级 A1~C1
    vocabulary_acc: float                         # 各维度正确率 0~1
    grammar_acc: float
    reading_acc: float
    analysis: dict[str, str]                      # 各维度能力分析文字
    level_detail: dict[str, str]                  # 各等级得分情况，如 {"A2": "2/2"}
    recommended_level: str                        # 推荐阅读难度等级
    recommendations: list[BookRecommendation]     # 匹配难度的书目
    created_at: datetime | None = None            # 提交即时返回时为 None；查库时为落库时间
