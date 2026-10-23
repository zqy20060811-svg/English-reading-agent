from fastapi import APIRouter, Depends

from app.schemas.ask import AskReadingRequest, AskRequest, AskResponse
from app.services.book_service import BookService, get_book_service
from app.services.llm_service import LLMService, get_llm_service
from app.services.retrieval_service import RetrievalService, get_retrieval_service
from app.services.user_service import get_current_user

router = APIRouter(prefix="/ask", tags=["AI 问答"])

# RAG 证据检索条数
READING_TOP_K = 5


@router.post("", response_model=AskResponse)
async def ask(
    req: AskRequest,
    service: LLMService = Depends(get_llm_service),
    current_user=Depends(get_current_user),  # 需登录：校验 Bearer token
):
    """向 DeepSeek 大模型提问（需登录后携带 Bearer token）"""
    answer = await service.ask(req.question)
    return AskResponse(answer=answer)


@router.post("/reading", response_model=AskResponse)
async def ask_reading(
    req: AskReadingRequest,
    llm: LLMService = Depends(get_llm_service),
    book_service: BookService = Depends(get_book_service),
    retrieval: RetrievalService = Depends(get_retrieval_service),
    current_user=Depends(get_current_user),  # 需登录：校验 Bearer token
):
    """基于 RAG 向量检索向大模型提问（需登录后携带 Bearer token）。

    产品规则（V1.1）：
    - 检索范围两阶段：优先当前章节；章内证据不足（命中少或距离偏大）时
      扩展到整本书补充证据，响应中 scope 标注实际范围
    - 全程零命中时直接拒答，不再回退整章原文——与「证据不足不编造」定位一致
    """
    book, chapter = await book_service.get_chapter(req.book_id, req.chapter_index)
    result = await retrieval.retrieve_with_scope(
        req.question, book_id=req.book_id, chapter_id=chapter.id,
        top_k=READING_TOP_K, rewriter=llm.rewrite_query,
    )
    if result.scope == "none":
        return AskResponse(
            answer=(
                "在本书相关章节中没有检索到与问题相关的内容，无法基于证据回答。"
                "建议换个问法，或先确认问题与本书内容相关。"
            ),
            scope="none",
        )
    answer = await llm.ask_with_context(req.question, result.context)
    return AskResponse(answer=answer, scope=result.scope)
