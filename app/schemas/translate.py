from pydantic import BaseModel, Field

# 单次翻译文本长度上限（控制 LLM 调用成本与超时风险）
MAX_TRANSLATE_CHARS = 5000


class TranslateRequest(BaseModel):
    """翻译请求：各类语言互译，默认自动检测源语言、译为中文"""

    text: str = Field(min_length=1, max_length=MAX_TRANSLATE_CHARS, description="待翻译文本")
    target_lang: str = Field(default="中文", min_length=1, max_length=30, description="目标语言")
    source_lang: str = Field(default="auto", min_length=1, max_length=30, description="源语言，auto 为自动检测")
    provider: str = Field(default="deepseek", min_length=1, max_length=30, description="翻译通道")


class TranslateResponse(BaseModel):
    """翻译结果"""

    translation: str
    provider: str
    char_count: int  # 计费口径：按输入字符数
