from fastapi import APIRouter, Depends

from app.schemas.ask import AskReadingRequest, AskRequest, AskResponse
from app.services.book_service import BookService, get_book_service
from app.services.llm_service import LLMService, get_llm_service
from app.services.user_service import get_current_user

router = APIRouter(prefix="/ask", tags=["AI 问答"])


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
    current_user=Depends(get_current_user),  # 需登录：校验 Bearer token
):
    """基于指定章节原文向大模型提问（需登录后携带 Bearer token）"""
    book, chapter = await book_service.get_chapter(req.book_id, req.chapter_index)
    answer = await llm.ask_with_context(req.question, chapter.content)
    return AskResponse(answer=answer)
