from fastapi import APIRouter, Depends, Query

from app.schemas.book import BookOut, BookSyncResult, ChapterDetailOut, ChapterOut
from app.services.book_service import BookService, get_book_service
from app.services.user_service import get_current_user

# 整个书籍路由均需登录：自动校验 Bearer token（JWT 合法且未在 Redis 登出）
router = APIRouter(
    prefix="/books",
    tags=["书籍"],
    dependencies=[Depends(get_current_user)],
)


@router.get("", response_model=list[BookOut])
async def list_books(
    limit: int = Query(default=200, ge=1, le=500, description="返回数量上限"),
    service: BookService = Depends(get_book_service),
):
    """全部书籍列表（按入库顺序，含简介），供前端书架使用"""
    return await service.list_all(limit)


@router.get("/search", response_model=list[BookOut])
async def search_books(
    title: str = Query(min_length=1, max_length=255, description="书名关键词"),
    service: BookService = Depends(get_book_service),
):
    """按书名模糊查询书籍信息与简介（完全匹配优先）"""
    return await service.search_by_title(title)


@router.get("/{book_id}/chapters", response_model=list[ChapterOut])
async def list_chapters(
    book_id: int,
    service: BookService = Depends(get_book_service),
):
    """获取一本书的章节目录（按章节序号排序，不含正文）"""
    book, chapters = await service.list_chapters(book_id)
    return chapters


@router.get("/{book_id}/chapters/{chapter_index}", response_model=ChapterDetailOut)
async def get_chapter(
    book_id: int,
    chapter_index: int,
    service: BookService = Depends(get_book_service),
):
    """获取指定章节正文"""
    book, chapter = await service.get_chapter(book_id, chapter_index)
    return chapter


@router.post("/sync", response_model=BookSyncResult)
async def sync_books(service: BookService = Depends(get_book_service)):
    """将本地爬取结果（data/books）的书籍信息与简介同步入库（不存正文）"""
    return await service.sync_from_crawler()
