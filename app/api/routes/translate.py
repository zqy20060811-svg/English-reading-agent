from fastapi import APIRouter, Depends

from app.schemas.translate import TranslateRequest, TranslateResponse
from app.services.translation_service import TranslationService, get_translation_service
from app.services.user_service import get_current_user

router = APIRouter(prefix="/translate", tags=["翻译"])


@router.post("", response_model=TranslateResponse)
async def translate(
    req: TranslateRequest,
    service: TranslationService = Depends(get_translation_service),
    current_user=Depends(get_current_user),  # 需登录：校验 Bearer token
):
    """调用大模型翻译任意语言的文本（需登录后携带 Bearer token）。

    源语言可 auto 自动检测，目标语言自由指定；每次调用记录用量供后续计费/配额。
    """
    return await service.translate(current_user.id, req)
