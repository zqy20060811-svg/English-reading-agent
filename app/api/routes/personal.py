"""个人书籍路由：上传 / 列表 / 详情 / 章节 / 正文 / 进度 / 删除。

全部接口要求登录；所有按 id 的操作都在业务层校验 user_id 归属，
他人书籍与不存在的书籍统一返回 404（不泄露存在性）。
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from app.core.config import get_settings
from app.schemas.personal_book import (
    PersonalBookOut,
    PersonalBookUploadOut,
    PersonalChapterDetailOut,
    PersonalChapterOut,
    PersonalProgressOut,
    PersonalProgressUpdate,
)
from app.services.personal_book_service import (
    PersonalBookService,
    get_personal_book_service,
)
from app.services.user_service import get_current_user

router = APIRouter(
    prefix="/personal/books",
    tags=["个人书籍"],
    dependencies=[Depends(get_current_user)],
)

_CHUNK = 1024 * 1024


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """分块读取上传内容并强制大小上限，避免超大文件占满内存"""
    chunks: list[bytes] = []
    total = 0
    while True:
        buf = await file.read(_CHUNK)
        if not buf:
            break
        total += len(buf)
        if total > max_bytes:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                f"文件超过上限 {get_settings().PERSONAL_MAX_UPLOAD_MB}MB",
            )
        chunks.append(buf)
    return b"".join(chunks)


@router.post("", response_model=PersonalBookUploadOut, status_code=status.HTTP_201_CREATED)
async def upload_personal_book(
    file: UploadFile = File(..., description="EPUB 或 TXT 文件"),
    service: PersonalBookService = Depends(get_personal_book_service),
    current_user=Depends(get_current_user),
):
    """上传个人电子书：同步解析结构，返回后即可阅读（不做 AI 分析）"""
    settings = get_settings()
    data = await _read_limited(file, settings.PERSONAL_MAX_UPLOAD_MB * 1024 * 1024)
    book, duplicated = await service.create_book(current_user, file.filename or "", data)
    out = PersonalBookUploadOut.model_validate(book)
    out.duplicated = duplicated
    return out


@router.get("", response_model=list[PersonalBookOut])
async def list_my_personal_books(
    service: PersonalBookService = Depends(get_personal_book_service),
    current_user=Depends(get_current_user),
):
    """我的个人书籍列表（按上传时间倒序）"""
    return await service.list_books(current_user)


@router.get("/{personal_book_id}", response_model=PersonalBookOut)
async def get_personal_book(
    personal_book_id: int,
    service: PersonalBookService = Depends(get_personal_book_service),
    current_user=Depends(get_current_user),
):
    """个人书籍详情（仅本人可见）"""
    return await service.get_book(current_user, personal_book_id)


@router.delete("/{personal_book_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_personal_book(
    personal_book_id: int,
    service: PersonalBookService = Depends(get_personal_book_service),
    current_user=Depends(get_current_user),
):
    """删除个人书籍：连带清理章节、阅读进度与磁盘原始文件"""
    await service.delete_book(current_user, personal_book_id)


@router.get("/{personal_book_id}/chapters", response_model=list[PersonalChapterOut])
async def list_personal_chapters(
    personal_book_id: int,
    service: PersonalBookService = Depends(get_personal_book_service),
    current_user=Depends(get_current_user),
):
    """章节目录（不含正文）"""
    return await service.list_chapters(current_user, personal_book_id)


@router.get(
    "/{personal_book_id}/chapters/{chapter_index}",
    response_model=PersonalChapterDetailOut,
)
async def get_personal_chapter(
    personal_book_id: int,
    chapter_index: int,
    service: PersonalBookService = Depends(get_personal_book_service),
    current_user=Depends(get_current_user),
):
    """章节正文"""
    return await service.get_chapter(current_user, personal_book_id, chapter_index)


@router.get("/{personal_book_id}/progress", response_model=PersonalProgressOut)
async def get_personal_progress(
    personal_book_id: int,
    service: PersonalBookService = Depends(get_personal_book_service),
    current_user=Depends(get_current_user),
):
    """读取上次阅读位置（无记录时返回初始进度）"""
    return await service.get_progress(current_user, personal_book_id)


@router.put("/{personal_book_id}/progress", response_model=PersonalProgressOut)
async def save_personal_progress(
    personal_book_id: int,
    data: PersonalProgressUpdate,
    service: PersonalBookService = Depends(get_personal_book_service),
    current_user=Depends(get_current_user),
):
    """保存阅读位置（章节 + 章内页码 + 全书百分比）"""
    return await service.save_progress(current_user, personal_book_id, data)
