from fastapi import APIRouter, Depends, Query

from app.schemas.book import BookOut, BookSyncResult
from app.services.book_service import BookService, get_book_service
from app.services.user_service import get_current_user

# 整个书籍路由均需登录：自动校验 Bearer token（JWT 合法且未在 Redis 登出）
router = APIRouter(
    prefix="/books",
    tags=["书籍"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/search", response_model=list[BookOut])
async def search_books(
    title: str = Query(min_length=1, max_length=255, description="书名关键词"),
    service: BookService = Depends(get_book_service),
):
    """按书名模糊查询书籍信息与简介（完全匹配优先）"""
    return await service.search_by_title(title)


@router.post("/sync", response_model=BookSyncResult)
async def sync_books(service: BookService = Depends(get_book_service)):
    """将本地爬取结果（data/books）的书籍信息与简介同步入库（不存正文）"""
    return await service.sync_from_crawler()
