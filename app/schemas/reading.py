from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ReadingProgressUpdate(BaseModel):
    """阅读进度上报"""

    chapter_index: int = Field(ge=1, description="读到第几章")
    char_offset: int = Field(ge=0, description="章内字符偏移")
    page_index: int = Field(ge=0, default=0, description="章内页码（0 起，前端分页粒度断点）")
    percent: float = Field(ge=0, le=100, description="全书阅读百分比")


class ReadingProgressOut(BaseModel):
    """阅读进度"""

    model_config = ConfigDict(from_attributes=True)

    book_id: int
    chapter_index: int
    char_offset: int
    page_index: int
    percent: float
    updated_at: datetime
