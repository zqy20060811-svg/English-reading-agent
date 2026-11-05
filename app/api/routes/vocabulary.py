import asyncio

from fastapi import APIRouter, Depends, status

from app.models.user import User
from app.schemas.study import (
    VocabularyAddRequest,
    VocabularyDefinitionsOut,
    VocabularyDefinitionsRequest,
    VocabularyGroupCreate,
    VocabularyGroupOut,
    VocabularyGroupUpdate,
    VocabularyMoveRequest,
    VocabularyOut,
    WordLookupResponse,
)
from app.services.lookup_service import LookupService, get_lookup_service
from app.services.user_service import get_current_user
from app.services.vocabulary_service import VocabularyService, get_vocabulary_service

# 生词本 + 点词查义路由（均需登录）
router = APIRouter(
    tags=["生词本"],
    dependencies=[Depends(get_current_user)],
)

# 批量释义时未缓存词的并发查模型上限（防止一次打满配额/连接）
_DEFINITION_CONCURRENCY = 4


@router.get("/vocabulary", response_model=list[VocabularyOut])
async def list_vocabulary(
    service: VocabularyService = Depends(get_vocabulary_service),
    current_user: User = Depends(get_current_user),
):
    """当前用户生词本列表（按收藏时间倒序，附带来源书名）"""
    return await service.list_words(current_user)


@router.post("/vocabulary/definitions", response_model=VocabularyDefinitionsOut)
async def vocabulary_definitions(
    req: VocabularyDefinitionsRequest,
    lookup_service: LookupService = Depends(get_lookup_service),
    current_user: User = Depends(get_current_user),
):
    """生词本批量释义：缓存优先（零成本），未缓存词受控并发调模型兜底。

    收藏过的词大概率在阅读时查过（已有 7 天缓存），多数请求零模型消耗；
    单个词失败（配额超限/无效词）返回 null，不影响整批。
    """
    # 去重 + 归一化（保持请求顺序）
    seen: dict[str, None] = {}
    for w in req.words:
        w = w.strip().lower()
        if w:
            seen.setdefault(w, None)
    words = list(seen.keys())[:50]

    sem = asyncio.Semaphore(_DEFINITION_CONCURRENCY)
    llm_queried: list[str] = []

    async def _one(word: str) -> tuple[str, WordLookupResponse | None]:
        cached = await lookup_service.lookup_cached_only(word)
        if cached is not None:
            return word, cached
        async with sem:
            try:
                result = await lookup_service.lookup(current_user.id, word)
            except Exception:  # 配额超限/无效词等：单查失败不阻塞整批
                return word, None
        llm_queried.append(word)
        return word, result

    pairs = await asyncio.gather(*(_one(w) for w in words))
    return VocabularyDefinitionsOut(
        definitions={w: r for w, r in pairs}, llm_queried=llm_queried
    )


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


# ---------- 生词本自定义分组 ----------

@router.get("/vocabulary/groups", response_model=list[VocabularyGroupOut])
async def list_vocabulary_groups(
    service: VocabularyService = Depends(get_vocabulary_service),
    current_user: User = Depends(get_current_user),
):
    """当前用户的生词分组列表（附各组词数，按设定顺序排列）"""
    return await service.list_groups(current_user)


@router.post("/vocabulary/groups", response_model=VocabularyGroupOut, status_code=status.HTTP_201_CREATED)
async def create_vocabulary_group(
    req: VocabularyGroupCreate,
    service: VocabularyService = Depends(get_vocabulary_service),
    current_user: User = Depends(get_current_user),
):
    """新建生词分组（名称用户内唯一，有数量上限）"""
    return await service.create_group(current_user, req)


@router.patch("/vocabulary/groups/{group_id}", response_model=VocabularyGroupOut)
async def update_vocabulary_group(
    group_id: int,
    req: VocabularyGroupUpdate,
    service: VocabularyService = Depends(get_vocabulary_service),
    current_user: User = Depends(get_current_user),
):
    """更新分组（重命名 / 调整展示顺序）"""
    return await service.update_group(current_user, group_id, req)


@router.delete("/vocabulary/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vocabulary_group(
    group_id: int,
    service: VocabularyService = Depends(get_vocabulary_service),
    current_user: User = Depends(get_current_user),
):
    """删除分组：组内生词自动回落到"未分组"，不丢词"""
    await service.delete_group(current_user, group_id)


@router.patch("/vocabulary/{word_id}/group", response_model=VocabularyOut)
async def move_vocabulary_word(
    word_id: int,
    req: VocabularyMoveRequest,
    service: VocabularyService = Depends(get_vocabulary_service),
    current_user: User = Depends(get_current_user),
):
    """移动生词到指定分组（group_id 传空 = 移回未分组）"""
    return await service.move_word(current_user, word_id, req.group_id)


@router.get("/lookup/word/{word}", response_model=WordLookupResponse)
async def lookup_word(
    word: str,
    service: LookupService = Depends(get_lookup_service),
    current_user: User = Depends(get_current_user),
):
    """点词查义：LLM 返回中文释义，结果缓存 7 天，命中缓存不消耗每日配额"""
    return await service.lookup(current_user.id, word)
