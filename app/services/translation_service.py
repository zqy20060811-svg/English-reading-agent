"""翻译业务逻辑：多通道 Provider 注册表 + 调用记录落库。

- 各类语言互译：源语言可 auto（由模型自动检测），目标语言自由指定
- 多通道预留：新翻译 API 只需实现一个 Provider 并在注册表登记，路由与调用方不变
- 付费预留：Provider 带 is_premium 标志，付费通道默认拒绝调用（后续放开时接订单/配额）
- 计量预留：每次调用写入 translation_records（字符数为计费口径），不限制用量
"""

from dataclasses import dataclass
from typing import Awaitable, Callable

from fastapi import Depends, HTTPException, status
from fastapi.concurrency import run_in_threadpool

from app.db.database import get_db
from app.models.translation_record import TranslationRecord
from app.repositories.translation_repository import TranslationRepository
from app.schemas.translate import TranslateRequest, TranslateResponse
from app.services.llm_service import LLMService, get_llm_service

# 翻译系统提示词：只输出译文，自动检测源语言，保留格式
TRANSLATE_SYSTEM_PROMPT = (
    "You are a professional translator.\n"
    "Rules:\n"
    "1. Translate the user's text into the requested target language.\n"
    "2. If the source language is 'auto', detect it automatically; otherwise use the "
    "given source language.\n"
    "3. Output ONLY the translation: no explanations, no quotes, no notes.\n"
    "4. Preserve the original formatting (line breaks, lists) and keep proper nouns, "
    "code snippets and URLs unchanged."
)


@dataclass(frozen=True)
class TranslateProvider:
    """翻译通道：name 为注册标识，is_premium 标记付费通道"""

    name: str
    translate: Callable[[str, str, str], Awaitable[str]]  # (text, target_lang, source_lang) -> 译文
    is_premium: bool = False


def _deepseek_translate(text: str, target_lang: str, source_lang: str) -> str:
    """DeepSeek 翻译（同步阻塞，由调用方放入线程池）"""
    user_content = (
        f"Target language: {target_lang}\n"
        f"Source language: {source_lang}\n\n"
        f"Text:\n{text}"
    )
    payload = LLMService._build_payload(TRANSLATE_SYSTEM_PROMPT, user_content)
    payload["temperature"] = 0.2
    return LLMService._request_chat(payload)


async def _deepseek_translate_async(text: str, target_lang: str, source_lang: str) -> str:
    return await run_in_threadpool(_deepseek_translate, text, target_lang, source_lang)


# 通道注册表：后续接入其他翻译 API（如百度翻译、火山引擎等）在此登记即可
_PROVIDERS: dict[str, TranslateProvider] = {
    "deepseek": TranslateProvider(
        name="deepseek", translate=_deepseek_translate_async, is_premium=False
    ),
}

# 默认免费通道
DEFAULT_PROVIDER = "deepseek"


class TranslationService:
    """翻译服务：通道选择 → 调用 → 记录落库"""

    def __init__(self, llm: LLMService, repo: TranslationRepository):
        self.llm = llm
        self.repo = repo

    async def translate(self, user_id: int, req: TranslateRequest) -> TranslateResponse:
        provider = _PROVIDERS.get(req.provider)
        if provider is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"未知翻译通道：{req.provider}（可用：{sorted(_PROVIDERS)}）",
            )
        # 付费通道预留：当前一律拒绝，后续接入订单/配额后放开
        if provider.is_premium:
            raise HTTPException(
                status.HTTP_402_PAYMENT_REQUIRED, f"付费翻译通道 {provider.name} 暂未开放"
            )

        translation = await provider.translate(req.text, req.target_lang, req.source_lang)

        await self.repo.save(
            TranslationRecord(
                user_id=user_id,
                provider=provider.name,
                source_lang=req.source_lang,
                target_lang=req.target_lang,
                char_count=len(req.text),
            )
        )
        return TranslateResponse(
            translation=translation, provider=provider.name, char_count=len(req.text)
        )


def get_translation_repository(db=Depends(get_db)) -> TranslationRepository:
    """FastAPI 依赖注入：构建翻译记录数据访问层"""
    return TranslationRepository(db)


def get_translation_service(
    llm: LLMService = Depends(get_llm_service),
    repo: TranslationRepository = Depends(get_translation_repository),
) -> TranslationService:
    """FastAPI 依赖注入：组装翻译服务（LLM 调用 + 记录落库）"""
    return TranslationService(llm, repo)
