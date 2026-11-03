from fastapi import APIRouter, Depends, status

from app.models.user import User
from app.schemas.study import BookmarkAddRequest, BookmarkOut
from app.services.bookmark_service import BookmarkService, get_bookmark_service
from app.services.user_service import get_current_user

# 书签路由（均需登录）
router = APIRouter(
    prefix="/bookmarks",
    tags=["书签"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[BookmarkOut])
async def list_bookmarks(
    book_id: int | None = None,
    service: BookmarkService = Depends(get_bookmark_service),
    current_user: User = Depends(get_current_user),
):
    """当前用户书签列表，可按书籍过滤（按添加时间倒序，附带书名）"""
    return await service.list_bookmarks(current_user, book_id)


@router.post("", response_model=BookmarkOut, status_code=status.HTTP_201_CREATED)
async def add_bookmark(
    req: BookmarkAddRequest,
    service: BookmarkService = Depends(get_bookmark_service),
    current_user: User = Depends(get_current_user),
):
    """添加书签（幂等：同一位置重复添加返回已有条目）"""
    return await service.add_bookmark(current_user, req)


@router.delete("/{bookmark_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_bookmark(
    bookmark_id: int,
    service: BookmarkService = Depends(get_bookmark_service),
    current_user: User = Depends(get_current_user),
):
    """删除书签"""
    await service.remove_bookmark(current_user, bookmark_id)
