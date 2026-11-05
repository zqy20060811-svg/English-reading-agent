"""封面图缓存代理：GET /covers/{book_id}（公开访问，无需登录）。

书库封面原图存放在 Open Library 等外部站点，直连访问慢且不稳定。
本接口把封面下载到本地 data/covers/ 长期缓存，并带一年 immutable 浏览器缓存；
同一本书的封面不变，按 book_id 缓存即可（ETag 命中直接 304）。
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.models.book import Book
from app.services.cover_service import ensure_cover_file, media_type_of

router = APIRouter(tags=["封面"])


@router.get("/covers/{book_id}")
async def get_cover(book_id: int, request: Request, db: AsyncSession = Depends(get_db)):
    book = (await db.execute(select(Book).where(Book.id == book_id))).scalar_one_or_none()
    if book is None or not book.is_active or not book.cover_url:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "封面不可用")
    etag = f'"cover-{book_id}"'
    headers = {"Cache-Control": "public, max-age=31536000, immutable", "ETag": etag}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    path = await ensure_cover_file(book.id, book.cover_url)
    return FileResponse(path, media_type=media_type_of(path), headers=headers)
