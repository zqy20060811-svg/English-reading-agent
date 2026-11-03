from fastapi import APIRouter, Depends, status

from app.models.user import User
from app.schemas.study import VocabularyAddRequest, VocabularyOut, WordLookupResponse
from app.services.lookup_service import LookupService, get_lookup_service
from app.services.user_service import get_current_user
from app.services.vocabulary_service import VocabularyService, get_vocabulary_service

# 生词本 + 点词查义路由（均需登录）
router = APIRouter(
    tags=["生词本"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/vocabulary", response_model=list[VocabularyOut])
async def list_vocabulary(
    service: VocabularyService = Depends(get_vocabulary_service),
    current_user: User = Depends(get_current_user),
):
    """当前用户生词本列表（按收藏时间倒序，附带来源书名）"""
    return await service.list_words(current_user)


@router.post("/vocabulary", response_model=VocabularyOut, status_code=status.HTTP_201_CREATED)
async def add_vocabulary(
    req: VocabularyAddRequest,
    service: VocabularyService = Depends(get_vocabulary_service),
    current_user: User = Depends(get_current_user),
):
    """收录生词（幂等：同一单词重复收录返回已有条目）"""
    return await service.add_word(current_user, req)


@router.delete("/vocabulary/{word_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_vocabulary(
    word_id: int,
    service: VocabularyService = Depends(get_vocabulary_service),
    current_user: User = Depends(get_current_user),
):
    """从生词本移除生词"""
    await service.remove_word(current_user, word_id)


@router.get("/lookup/word/{word}", response_model=WordLookupResponse)
async def lookup_word(
    word: str,
    service: LookupService = Depends(get_lookup_service),
    current_user: User = Depends(get_current_user),
):
    """点词查义：LLM 返回中文释义，结果缓存 7 天，命中缓存不消耗每日配额"""
    return await service.lookup(current_user.id, word)
