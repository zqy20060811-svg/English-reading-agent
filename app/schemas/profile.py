"""个人中心相关 Schema"""

from datetime import datetime

from pydantic import BaseModel, Field


class UserStatsOut(BaseModel):
    """个人中心统计概览"""

    read_books: int          # 读过的书（有阅读进度的书数）
    chapters_finished: int   # 正在读/读过的章节数（进度行总数）
    liked_count: int         # 点赞过的书数
    favorite_count: int      # 收藏过的书数
    translation_count: int   # 翻译调用次数
    translation_chars: int   # 翻译累计字符数（计费口径）
    level: str | None        # 最近一次英语水平测试等级（未测试为 null）


class HistoryItemOut(BaseModel):
    """最近阅读条目（含书籍信息与进度）"""

    book_id: int
    title: str
    author: str
    cover_url: str | None
    chapter_index: int
    percent: float
    updated_at: datetime


class PasswordChangeRequest(BaseModel):
    """修改密码请求"""

    old_password: str = Field(min_length=6, max_length=64)
    new_password: str = Field(min_length=6, max_length=64)


class UserSettingsOut(BaseModel):
    """用户设置（读取）"""

    target_lang: str


class UserSettingsUpdateRequest(BaseModel):
    """用户设置（更新）"""

    target_lang: str = Field(min_length=1, max_length=30)
