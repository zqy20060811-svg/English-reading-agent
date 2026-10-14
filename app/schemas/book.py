from datetime import datetime

from pydantic import BaseModel, ConfigDict


class BookOut(BaseModel):
    """书籍信息（含简介，不含正文）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    gutenberg_id: int
    title: str
    author: str
    year: int
    genre: str
    synopsis: str
    language: str
    source_url: str
    word_count: int
    created_at: datetime


class BookSyncResult(BaseModel):
    """从爬取结果同步入库的统计"""

    total_found: int   # 本地目录中发现的书籍数
    created: int       # 新增入库数量
    updated: int       # 更新数量


class ChapterOut(BaseModel):
    """章节目录项（不含正文）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    chapter_index: int
    title: str
    word_count: int


class ChapterDetailOut(ChapterOut):
    """章节详情（含正文）"""

    content: str
