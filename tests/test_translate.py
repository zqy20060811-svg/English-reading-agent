"""翻译服务单元测试（不依赖数据库与真实 LLM，用假 Provider / 假 Repository 隔离）。"""

import asyncio

import pytest
from fastapi import HTTPException

from app.schemas.translate import MAX_TRANSLATE_CHARS, TranslateRequest
from app.services.translation_service import (
    DEFAULT_PROVIDER,
    TranslateProvider,
    TranslationService,
)


class FakeRepo:
    def __init__(self):
        self.saved = []

    async def save(self, record):
        record.id = len(self.saved) + 1
        self.saved.append(record)
        return record

    async def count_recent(self, user_id):
        return sum(1 for r in self.saved if r.user_id == user_id)


async def _fake_translate(text: str, target_lang: str, source_lang: str) -> str:
    return f"[{target_lang}] {text}"


async def _make_service(provider: TranslateProvider | None = None) -> TranslationService:
    provider = provider or TranslateProvider(name="fake", translate=_fake_translate)
    service = TranslationService(llm=None, repo=FakeRepo())
    # 测试用：把假通道注册到其名字下（真实服务的 _PROVIDERS 为模块级注册表）
    import app.services.translation_service as mod

    mod._PROVIDERS[provider.name] = provider
    return service


def test_translate_basic_and_record():
    service = asyncio.run(_make_service())
    req = TranslateRequest(text="Hello world", target_lang="中文", provider="fake")
    result = asyncio.run(service.translate(user_id=1, req=req))
    assert result.translation == "[中文] Hello world"
    assert result.provider == "fake" and result.char_count == len("Hello world")
    # 调用已落库：用户、通道、语言对、字符数
    row = service.repo.saved[0]
    assert row.user_id == 1 and row.provider == "fake"
    assert row.source_lang == "auto" and row.target_lang == "中文"
    assert row.char_count == len("Hello world")


def test_translate_unknown_provider_rejected():
    service = asyncio.run(_make_service())
    req = TranslateRequest(text="hi", provider="no-such")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.translate(user_id=1, req=req))
    assert exc.value.status_code == 400


def test_translate_premium_provider_blocked():
    # 付费通道预留：即使注册了也默认拒绝（402）
    service = asyncio.run(_make_service(TranslateProvider(name="paid", translate=_fake_translate, is_premium=True)))
    req = TranslateRequest(text="hi", provider="paid")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(service.translate(user_id=1, req=req))
    assert exc.value.status_code == 402


def test_translate_text_length_limit():
    with pytest.raises(ValueError):
        # 超过单次上限的请求在校验层直接拒绝
        TranslateRequest(text="a" * (MAX_TRANSLATE_CHARS + 1))


def test_default_provider_registered():
    # 默认通道必须真实存在（DeepSeek），保证生产可用
    import app.services.translation_service as mod

    assert DEFAULT_PROVIDER in mod._PROVIDERS
    assert mod._PROVIDERS[DEFAULT_PROVIDER].is_premium is False
