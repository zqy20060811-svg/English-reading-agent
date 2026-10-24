from typing import Literal

from pydantic import BaseModel


class InteractionStateOut(BaseModel):
    """点赞/收藏状态与计数（toggle 接口与查询共用同一结构）"""

    liked: bool
    favorited: bool
    like_count: int
    favorite_count: int


class HotBreakdown(BaseModel):
    """热度分项：统计窗口（3 倍半衰期）内的行为量"""

    views: int
    finish_chapters: int
    likes: int
    favorites: int


class HotBookItem(BaseModel):
    """热门榜单条目"""

    rank: int
    book_id: int
    title: str
    author: str
    cover_url: str | None = None
    score: float


class BookHotDetailOut(BaseModel):
    """单本书热度详情（含分项统计与当前用户互动状态）"""

    book_id: int
    score: float
    rank: int | None = None  # 未上榜时为 None
    breakdown: HotBreakdown
    liked: bool
    favorited: bool
    like_count: int
    favorite_count: int


class BookEventIn(BaseModel):
    """阅读行为上报：浏览由后端自动埋点，前端仅上报读完章节"""

    event_type: Literal["finish_chapter"]
