"""个人书籍 AI 全书分析接口模型"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class PersonalAnalysisTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    personal_book_id: int
    status: str
    total_chapters: int
    completed_chapters: int
    failed_chapters: int
    current_chapter_index: int | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class PersonalChapterAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    chapter_index: int
    word_count: int
    unique_word_count: int
    average_sentence_length: float
    long_sentence_ratio: float
    vocabulary_level_distribution: dict
    vocabulary_statistics: dict
    grammar_features: dict
    difficulty_level: str
    difficulty_score: float
    chapter_summary: str
    reading_suggestion: str
    analysis_version: int
    updated_at: datetime


class PersonalBookAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    overall_level: str
    difficulty_score: float
    total_word_count: int
    chapter_difficulty_distribution: dict
    vocabulary_level_distribution: dict
    main_grammar_features: dict
    reading_recommendations: list
    analysis_version: int
    completed_at: datetime
