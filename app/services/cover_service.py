"""封面图本地缓存：外部封面 URL（Open Library 等）只下载一次，落盘 data/covers/ 长期复用。

外部直连访问慢且不稳定；本地缓存后书库展示全部走后端与浏览器长缓存。
"""

from pathlib import Path

import httpx
from fastapi import HTTPException, status

from app.core.config import get_settings

# 允许落盘的图片类型（Open Library 返回 JPEG，宽松兼容常见格式）
_EXT_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
}
_MEDIA_TYPE_BY_EXT = {v: k for k, v in _EXT_BY_CONTENT_TYPE.items()}
_MAX_COVER_BYTES = 5 * 1024 * 1024  # 5MB：远超真实封面大小，防御异常响应


def covers_dir() -> Path:
    path = Path(get_settings().COVER_CACHE_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def local_cover_path(book_id: int) -> Path | None:
    """已落盘封面路径（任意支持格式），不存在返回 None"""
    for ext in _EXT_BY_CONTENT_TYPE.values():
        p = covers_dir() / f"{book_id}{ext}"
        if p.exists():
            return p
    return None


def media_type_of(path: Path) -> str:
    return _MEDIA_TYPE_BY_EXT.get(path.suffix.lower(), "image/jpeg")


async def ensure_cover_file(book_id: int, cover_url: str) -> Path:
    """返回本地封面文件：已缓存直接命中，未缓存从源站下载一次并落盘。

    下载失败/响应不合法时抛 404，由前端渐变占位兜底，不影响书库展示。
    """
    cached = local_cover_path(book_id)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(cover_url)
    except httpx.HTTPError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "封面源站不可达")
    content_type = (resp.headers.get("content-type") or "").split(";")[0].strip().lower()
    if (
        resp.status_code != 200
        or content_type not in _EXT_BY_CONTENT_TYPE
        or not resp.content
        or len(resp.content) > _MAX_COVER_BYTES
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "封面不可用")
    path = covers_dir() / f"{book_id}{_EXT_BY_CONTENT_TYPE[content_type]}"
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(resp.content)
    tmp.replace(path)  # 原子替换，避免并发请求读到半截文件
    return path
