"""个人书籍个性化预测接口模型（阶段C：生词预测 + 长难句预测）"""

from pydantic import BaseModel


class PredictedWord(BaseModel):
    """生词候选"""

    word: str            # 归一化小写
    level: str           # CEFR 等级（A1~C2），词典未收录为 unknown
    count: int           # 在本章出现次数
    in_vocabulary: bool  # 是否已在用户生词本中（用户确认过的生词）


class PredictedSentence(BaseModel):
    """长难句候选"""

    sentence_index: int        # 句子在章节中的序号（1 开始）
    char_start: int | None     # 章节正文中的字符偏移（定位失败为 None）
    word_count: int            # 句子词数
    clause_markers: int        # 从句标记数量（启发式计数）
    text: str                  # 句子原文


class ChapterPrediction(BaseModel):
    """单章预测结果"""

    chapter_index: int
    title: str
    words: list[PredictedWord]
    sentences: list[PredictedSentence]


class BookPrediction(BaseModel):
    """全书预测结果（逐章汇总）"""

    personal_book_id: int
    user_level: str       # 用户当前英语水平（A1~C1 或默认 B1）
    level_source: str     # test = 等级测试结果；default = 未测试默认值
    total_chapters: int
    chapters: list[ChapterPrediction]
