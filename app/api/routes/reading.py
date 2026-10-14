from fastapi import APIRouter, Depends

from app.schemas.reading import ReadingProgressOut, ReadingProgressUpdate
from app.services.reading_service import ReadingService, get_reading_service
from app.services.user_service import get_current_user

# 整个阅读进度路由均需登录：自动校验 Bearer token
router = APIRouter(
    prefix="/reading",
    tags=["阅读进度"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/progress/{book_id}", response_model=ReadingProgressOut)
async def get_progress(
    book_id: int,
    service: ReadingService = Depends(get_reading_service),
    current_user=Depends(get_current_user),
):
    """获取当前用户在某本书的上次阅读位置"""
    return await service.get_progress(current_user, book_id)


@router.put("/progress/{book_id}", response_model=ReadingProgressOut)
async def save_progress(
    book_id: int,
    data: ReadingProgressUpdate,
    service: ReadingService = Depends(get_reading_service),
    current_user=Depends(get_current_user),
):
    """保存当前阅读位置（章节序号、章内字符偏移、全书百分比），每人每书一行"""
    return await service.save_progress(current_user, book_id, data)
