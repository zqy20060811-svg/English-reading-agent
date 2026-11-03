"""后台管理接口的请求/响应模型"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


# ================= 用户管理 =================


class AdminUserOut(BaseModel):
    """后台用户列表项（管理员视角，含完整邮箱）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str
    email_verified: bool
    is_admin: bool
    is_disabled: bool
    created_at: datetime


class AdminUserUpdate(BaseModel):
    """用户管理操作：可改管理员标记 / 禁用状态，字段全部可选"""

    is_admin: bool | None = Field(default=None, description="设为管理员/取消管理员")
    is_disabled: bool | None = Field(default=None, description="禁用/解禁（禁用同时吊销其全部 token）")


# ================= 书籍上下架 =================


class AdminBookOut(BaseModel):
    """后台书籍列表项（含下架书籍，多 is_active 字段）"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    gutenberg_id: int
    title: str
    author: str
    year: int
    genre: str
    word_count: int
    is_active: bool


class AdminBookUpdate(BaseModel):
    is_active: bool = Field(description="上架/下架")


# ================= 入库任务 =================


class IngestTaskCreate(BaseModel):
    """创建入库任务：指定古登堡书号（须在 BOOK_CATALOG 中登记）"""

    gutenberg_id: int = Field(gt=0, description="古登堡书号")
    embed: bool = Field(default=False, description="是否同时向量化（CPU 慢，约 2.4 块/秒）")


class IngestTaskOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gutenberg_id: int
    embed: bool
    status: str          # pending / running / success / failed
    attempts: int
    error: str | None = None
    created_by: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


# ================= AI 用量统计 =================


class SceneUsageOut(BaseModel):
    """单场景的用量汇总"""

    scene: str
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class DailyUsageOut(BaseModel):
    """单日用量（全部场景合计）"""

    day: str             # YYYY-MM-DD（UTC）
    calls: int
    prompt_tokens: int
    completion_tokens: int
    cost_usd: float


class AIStatsOut(BaseModel):
    """AI 调用次数与成本统计（按天查询）"""

    days: int
    total_calls: int
    total_prompt_tokens: int
    total_completion_tokens: int
    total_cost_usd: float
    by_scene: list[SceneUsageOut]
    by_day: list[DailyUsageOut]


# ================= 概览 =================


class AdminOverviewOut(BaseModel):
    total_users: int
    total_books: int
    active_books: int
    running_or_pending_tasks: int
    ai_calls_today: int
