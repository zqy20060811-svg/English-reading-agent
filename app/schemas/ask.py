from pydantic import BaseModel, Field


class AskRequest(BaseModel):
    """提问请求"""

    question: str = Field(min_length=1, max_length=2000, description="用户的问题")


class AskResponse(BaseModel):
    """大模型回答"""

    answer: str
