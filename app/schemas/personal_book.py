from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PersonalBookOut(BaseModel):
    """个人书籍信息（不含正文）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    author: str
    language: str
    source_type: str
    original_filename: str
    file_size: int
    word_count: int
    chapter_count: int
    created_at: datetime
    has_cover: bool = False  # 是否有内嵌封面（前端决定用封面图还是默认占位）


class PersonalBookUploadOut(PersonalBookOut):
    """上传结果：duplicated 表示命中同人重复文件，直接复用已有记录"""

    duplicated: bool = False


class PersonalChapterOut(BaseModel):
    """个人书籍章节目录项"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    chapter_index: int
    title: str
    word_count: int


class PersonalChapterDetailOut(PersonalChapterOut):
    """个人书籍章节详情（含正文）"""

    content: str


class PersonalProgressUpdate(BaseModel):
    """个人书籍阅读进度上报"""

    chapter_index: int = Field(ge=1)
    char_offset: int = Field(ge=0)
    page_index: int = Field(ge=0, default=0)
    percent: float = Field(ge=0, le=100)


class PersonalProgressOut(BaseModel):
    """个人书籍阅读进度"""

    model_config = ConfigDict(from_attributes=True)

    personal_book_id: int
    chapter_index: int
    char_offset: int
    page_index: int
    percent: float
    updated_at: datetime
