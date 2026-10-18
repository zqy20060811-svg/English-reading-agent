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

    流程：校验书籍/章节存在 → 查询改写（中文问题转英文检索查询，失败回退原问题）→
    在该书内混合检索与问题最相关的文本块 → 把证据片段连同问题交给 DeepSeek，
    要求只基于证据回答、不足时明确说明。
    """
    book, chapter = await book_service.get_chapter(req.book_id, req.chapter_index)
    result = await retrieval.retrieve_for_question(
        req.question, book_id=req.book_id, top_k=READING_TOP_K, rewriter=llm.rewrite_query
    )
    # 检索无命中时退回当前章节原文，保证接口始终有上下文可用
    context = result.context if result.hits else f"[Current chapter {chapter.title}]\n{chapter.content}"
    answer = await llm.ask_with_context(req.question, context)
    return AskResponse(answer=answer)
