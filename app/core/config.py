from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置，从项目根目录 .env 读取"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    DATABASE_URL: str
    REDIS_URL: str
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    # Access Token 短时效（分钟），Refresh Token 长时效（天）
    JWT_ACCESS_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # DeepSeek 大模型配置
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL: str = "deepseek-chat"
    # DeepSeek 定价（美元 / 百万 tokens），供后台成本统计估算
    LLM_INPUT_PRICE_PER_M: float = 0.27
    LLM_OUTPUT_PRICE_PER_M: float = 1.10

    # SMTP 邮件配置：留空时验证码走 console 输出（开发环境）
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    # 邮箱验证码有效期（秒）
    EMAIL_CODE_TTL: int = 600

    # 每用户每日基础配额（商业化的计费预留口径）
    QUOTA_TRANSLATE_DAILY: int = 50
    QUOTA_ASK_DAILY: int = 50
    QUOTA_LOOKUP_DAILY: int = 100
    # 登录失败锁定：15 分钟窗口内最多失败次数
    LOGIN_FAIL_LIMIT: int = 5
    LOGIN_FAIL_WINDOW_SECONDS: int = 900

    # 个人电子书（用户上传的私人阅读材料，与公共书库完全隔离）
    PERSONAL_BOOKS_DIR: str = "data/personal"   # 原始文件存放目录（data/ 已在 gitignore）
    COVER_CACHE_DIR: str = "data/covers"        # 书库封面图本地缓存目录（外站原图只下载一次）
    PERSONAL_MAX_UPLOAD_MB: int = 20            # 单个文件上限（MB）
    PERSONAL_MAX_BOOKS_PER_USER: int = 20       # 每用户书籍数量上限
    PERSONAL_MAX_TOTAL_MB_PER_USER: int = 200   # 每用户占用空间上限（MB）

    # 个人电子书 AI 全书预分析（后台任务，按章节分析）
    PERSONAL_ANALYSIS_VERSION: int = 1          # 分析策略版本（调整策略后递增即可重分析）
    PERSONAL_ANALYSIS_MAX_LLM_CHARS: int = 12000  # 单章注入 LLM 的正文上限（超出截断保留开头）
    PERSONAL_ANALYSIS_LLM_MAX_TOKENS: int = 1800  # 单次分析调用的输出 token 上限
    PERSONAL_ANALYSIS_STALE_HOURS: int = 6      # running 超过该时长视为挂死（查询时懒惰标记失败）


@lru_cache
def get_settings() -> Settings:
    return Settings()
