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
    # 公共书必传；个人书籍收录时不传（个人书不在公共 books 表）
    book_id: int | None = Field(default=None, gt=0, description="收录时所在公共书籍 id（个人书为空）")
    chapter_index: int = Field(default=1, ge=1, description="收录时所在章节")
    context_sentence: str | None = Field(
        default=None, max_length=MAX_CONTEXT_LEN, description="收录时的上下文例句（可选）"
    )


class VocabularyOut(BaseModel):
    """生词条目"""

    model_config = {"from_attributes": True}

    id: int
    book_id: int | None
    book_title: str = ""  # 联表补充，便于展示来源（个人书收录为空）
    word: str
    context_sentence: str | None
    chapter_index: int
    group_id: int | None = None  # 自定义分组（null=未分组）
    created_at: datetime


class VocabularyDefinitionsRequest(BaseModel):
    """生词本批量释义请求（生词本页一次性拉取可见词的释义）"""

    words: list[str] = Field(min_length=1, max_length=50, description="待查单词列表（最多 50 个）")


class VocabularyDefinitionsOut(BaseModel):
    """生词本批量释义结果：word → 释义；查不到（配额超限/无效词）为 null"""

    definitions: dict[str, WordLookupResponse | None]
    llm_queried: list[str] = Field(default_factory=list, description="本次实际调用模型查询的词")


# ================= 生词本自定义分组 =================

MAX_VOCAB_GROUPS = 20  # 每用户分组数上限（防滥用，生词本分组不需要太多）


class VocabularyGroupCreate(BaseModel):
    """新建分组"""

    name: str = Field(min_length=1, max_length=32, description="分组名（用户内唯一）")


class VocabularyGroupUpdate(BaseModel):
    """更新分组（重命名 / 调整顺序；字段均可选）"""

    name: str | None = Field(default=None, min_length=1, max_length=32)
    position: int | None = Field(default=None, ge=0, le=9999)


class VocabularyGroupOut(BaseModel):
    """分组条目（附词数，供分组筛选栏展示）"""

    model_config = {"from_attributes": True}

    id: int
    name: str
    position: int
    word_count: int = 0


class VocabularyMoveRequest(BaseModel):
    """移动生词到分组（group_id 为空 = 移回未分组）"""

    group_id: int | None = Field(default=None, gt=0)


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
