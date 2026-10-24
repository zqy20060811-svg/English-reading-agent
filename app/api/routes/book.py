from fastapi import APIRouter, BackgroundTasks, Depends, Query

from app.schemas.book import BookOut, BookSyncResult, ChapterDetailOut, ChapterOut
from app.schemas.hotness import (
    BookEventIn,
    BookHotDetailOut,
    HotBookItem,
    InteractionStateOut,
)
from app.services.book_service import BookService, get_book_service
from app.services.hotness_service import (
    HotnessService,
    get_hotness_service,
    record_view_in_background,
)
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


@router.get("/mine", response_model=list[BookOut])
async def my_books(
    service: BookService = Depends(get_book_service),
    current_user=Depends(get_current_user),
):
    """当前用户的书单：读过/点赞过/收藏过的书（阅读页「选择一本书」下拉数据源）"""
    return await service.list_my_books(current_user.id)


@router.get("/hot", response_model=list[HotBookItem])
async def hot_ranking(
    limit: int = Query(default=20, ge=1, le=100, description="榜单数量上限"),
    service: HotnessService = Depends(get_hotness_service),
):
    """热门书籍榜单：浏览/读完章节/点赞/收藏加权 + 14 天半衰期衰减，Redis 缓存 10 分钟"""
    return await service.get_ranking(limit)


@router.get("/{book_id}/hot", response_model=BookHotDetailOut)
async def book_hotness(
    book_id: int,
    service: HotnessService = Depends(get_hotness_service),
    current_user=Depends(get_current_user),
):
    """单本书热度详情：总分、分项行为计数、榜单排名与当前用户点赞/收藏状态"""
    return await service.get_book_hotness(book_id, current_user.id)


@router.post("/{book_id}/like", response_model=InteractionStateOut)
async def toggle_like(
    book_id: int,
    service: HotnessService = Depends(get_hotness_service),
    current_user=Depends(get_current_user),
):
    """切换点赞状态（已赞则取消），返回最新状态与计数"""
    return await service.toggle_interaction(book_id, current_user.id, "like")


@router.post("/{book_id}/favorite", response_model=InteractionStateOut)
async def toggle_favorite(
    book_id: int,
    service: HotnessService = Depends(get_hotness_service),
    current_user=Depends(get_current_user),
):
    """切换收藏状态（已收藏则取消），返回最新状态与计数"""
    return await service.toggle_interaction(book_id, current_user.id, "favorite")


@router.post("/{book_id}/events", status_code=204)
async def report_event(
    book_id: int,
    data: BookEventIn,
    service: HotnessService = Depends(get_hotness_service),
    current_user=Depends(get_current_user),
):
    """前端上报阅读行为事件（如从章末页进入下一章时上报读完章节），同人同书每日限计 1 次"""
    await service.record_event(book_id, current_user.id, data.event_type)


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
    background_tasks: BackgroundTasks,
    service: BookService = Depends(get_book_service),
    current_user=Depends(get_current_user),
):
    """获取指定章节正文（同时后台记录一次浏览热度事件，同人同书每日限计 1 次）"""
    book, chapter = await service.get_chapter(book_id, chapter_index)
    background_tasks.add_task(record_view_in_background, book_id, current_user.id)
    return chapter


@router.post("/sync", response_model=BookSyncResult)
async def sync_books(service: BookService = Depends(get_book_service)):
    """将本地爬取结果（data/books）的书籍信息与简介同步入库（不存正文）"""
    return await service.sync_from_crawler()
