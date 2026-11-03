"""生词本 / 书签 / 点词查义的数据契约"""

from datetime import datetime

from pydantic import BaseModel, Field

# 生词归一化后长度上限（英文单词一般不超过 30 字符，留余量）
MAX_WORD_LEN = 64
# 收录生词时携带的上下文例句长度上限
MAX_CONTEXT_LEN = 500


# ================= 生词本 =================

class VocabularyAddRequest(BaseModel):
    """收录生词请求"""

    word: str = Field(min_length=1, max_length=MAX_WORD_LEN, description="生词（将归一化为小写）")
    book_id: int = Field(gt=0, description="收录时所在书籍 id")
    chapter_index: int = Field(default=1, ge=1, description="收录时所在章节")
    context_sentence: str | None = Field(
        default=None, max_length=MAX_CONTEXT_LEN, description="收录时的上下文例句（可选）"
    )


class VocabularyOut(BaseModel):
    """生词条目"""

    model_config = {"from_attributes": True}

    id: int
    book_id: int
    book_title: str = ""  # 联表补充，便于展示来源
    word: str
    context_sentence: str | None
    chapter_index: int
    created_at: datetime


# ================= 书签 =================

class BookmarkAddRequest(BaseModel):
    """添加书签请求"""

    book_id: int = Field(gt=0, description="书籍 id")
    chapter_index: int = Field(ge=1, description="书签所在章节")
    page_index: int = Field(ge=0, default=0, description="章内页码（0 起）")
    excerpt: str = Field(default="", max_length=200, description="所在页摘要（展示用）")


class BookmarkOut(BaseModel):
    """书签条目"""

    model_config = {"from_attributes": True}

    id: int
    book_id: int
    book_title: str = ""  # 联表补充
    chapter_index: int
    page_index: int
    excerpt: str
    created_at: datetime


# ================= 点词查义 =================

class WordLookupResponse(BaseModel):
    """单词释义结果（LLM 查词，缓存后重复查询不再消耗配额）"""

    word: str
    phonetic: str = ""  # 音标（可能为空）
    senses: list[str] = Field(default_factory=list, description="中文释义列表（按词性分组）")
    example_en: str = ""  # 英文例句
    example_cn: str = ""  # 例句中文翻译
    cached: bool = False  # 是否命中缓存（未消耗当日配额）
