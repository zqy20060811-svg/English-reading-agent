from fastapi import APIRouter, Depends

from app.schemas.ask import AskRequest, AskResponse
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
