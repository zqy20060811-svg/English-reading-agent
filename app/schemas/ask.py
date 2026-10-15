from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """提问请求"""

    question: str = Field(min_length=1, max_length=2000, description="用户的问题")


class AskReadingRequest(BaseModel):
    """基于章节原文的提问请求"""

    book_id: int = Field(ge=1, description="书籍 ID")
    chapter_index: int = Field(ge=1, description="章节序号")
    question: str = Field(min_length=1, max_length=2000, description="关于该章节的问题")


class AskResponse(BaseModel):
    """大模型回答"""

    answer: str
