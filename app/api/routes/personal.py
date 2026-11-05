"""个人书籍路由：上传 / 列表 / 详情 / 章节 / 正文 / 进度 / 删除。

全部接口要求登录；所有按 id 的操作都在业务层校验 user_id 归属，
他人书籍与不存在的书籍统一返回 404（不泄露存在性）。
"""

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse

from app.core.config import get_settings
from app.schemas.personal_analysis import (
    PersonalAnalysisTaskOut,
    PersonalBookAnalysisOut,
    PersonalChapterAnalysisOut,
)
from app.schemas.personal_prediction import BookPrediction, ChapterPrediction
from app.schemas.personal_book import (
    PersonalBookOut,
    PersonalBookUploadOut,
    PersonalChapterDetailOut,
    PersonalChapterOut,
    PersonalProgressOut,
    PersonalProgressUpdate,
)
from app.services.cover_service import media_type_of
from app.services.personal_analysis_service import (
    PersonalAnalysisService,
    get_personal_analysis_service,
)
from app.services.personal_book_service import (
    PersonalBookService,
    get_personal_book_service,
)
from app.services.personal_prediction_service import (
    PersonalPredictionService,
    get_personal_prediction_service,
)
from app.services.user_service import (
    get_current_user,
    get_current_user_flexible,
)

router = APIRouter(
    prefix="/personal/books",
    tags=["个人书籍"],
    dependencies=[Depends(get_current_user)],
)

# 封面路由单独挂载：供 <img> 标签加载，无法携带 Authorization 头，
# 使用 get_current_user_flexible（Bearer 头或 ?token= 均可）
cover_router = APIRouter(prefix="/personal/books", tags=["个人书籍"])

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
    analysis_service: PersonalAnalysisService = Depends(get_personal_analysis_service),
    current_user=Depends(get_current_user),
):
    """上传个人电子书：同步解析结构，返回后即可阅读（不做 AI 分析）"""
    settings = get_settings()
    data = await _read_limited(file, settings.PERSONAL_MAX_UPLOAD_MB * 1024 * 1024)
    book, duplicated = await service.create_book(current_user, file.filename or "", data)
    out = PersonalBookUploadOut.model_validate(book)
    out.duplicated = duplicated
    # 上传成功（含重复文件命中）后自动创建全书 AI 分析任务：
    # 后台异步执行，不阻塞本次响应；失败只记录日志，不影响阅读
    try:
        await analysis_service.ensure_task(current_user, book.id)
    except Exception:  # 分析任务创建失败不影响上传结果
        import logging

        logging.getLogger("app.personal_analysis").exception(
            "上传后自动创建分析任务失败：book=%s", book.id
        )
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


@cover_router.get("/{personal_book_id}/cover")
async def get_personal_book_cover(
    personal_book_id: int,
    service: PersonalBookService = Depends(get_personal_book_service),
    current_user=Depends(get_current_user_flexible),
):
    """个人书籍内嵌封面图（仅本人可访问；无封面 404，前端回退默认占位样式）

    独立路由不走 Bearer 头全局鉴权：<img> 标签带不了请求头，
    前端通过 ?token=<jwt> 传递，后端同样校验 JWT + Redis 存在性。
    """
    path = await service.get_cover_path(current_user, personal_book_id)
    return FileResponse(
        path,
        media_type=media_type_of(path),
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


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


# ================= AI 全书预分析 =================


@router.post("/{personal_book_id}/analysis", response_model=PersonalAnalysisTaskOut)
async def create_or_get_analysis_task(
    personal_book_id: int,
    service: PersonalAnalysisService = Depends(get_personal_analysis_service),
    current_user=Depends(get_current_user),
):
    """创建或获取全书分析任务（上传后已自动创建；失败/取消的任务可再次触发续跑）"""
    return await service.ensure_task(current_user, personal_book_id)


@router.get("/{personal_book_id}/analysis/status", response_model=PersonalAnalysisTaskOut)
async def get_analysis_status(
    personal_book_id: int,
    service: PersonalAnalysisService = Depends(get_personal_analysis_service),
    current_user=Depends(get_current_user),
):
    """查询分析任务状态与进度"""
    return await service.get_status(current_user, personal_book_id)


@router.get("/{personal_book_id}/analysis/report", response_model=PersonalBookAnalysisOut)
async def get_analysis_report(
    personal_book_id: int,
    service: PersonalAnalysisService = Depends(get_personal_analysis_service),
    current_user=Depends(get_current_user),
):
    """全书难度分析报告（章节分析全部完成后生成）"""
    return await service.get_report(current_user, personal_book_id)


@router.get(
    "/{personal_book_id}/analysis/chapters/{chapter_index}",
    response_model=PersonalChapterAnalysisOut,
)
async def get_chapter_analysis(
    personal_book_id: int,
    chapter_index: int,
    service: PersonalAnalysisService = Depends(get_personal_analysis_service),
    current_user=Depends(get_current_user),
):
    """指定章节的分析结果"""
    return await service.get_chapter_result(current_user, personal_book_id, chapter_index)


@router.post("/{personal_book_id}/analysis/cancel", response_model=PersonalAnalysisTaskOut)
async def cancel_analysis_task(
    personal_book_id: int,
    service: PersonalAnalysisService = Depends(get_personal_analysis_service),
    current_user=Depends(get_current_user),
):
    """取消进行中的分析任务（后台执行体感知后停止）"""
    return await service.cancel_task(current_user, personal_book_id)


# ================= 个性化预测（阶段C：生词 + 长难句） =================


@router.get("/{personal_book_id}/prediction", response_model=BookPrediction)
async def get_book_prediction(
    personal_book_id: int,
    service: PersonalPredictionService = Depends(get_personal_prediction_service),
    current_user=Depends(get_current_user),
):
    """全书个性化预测：基于用户英语水平预测每章可能的生词与长难句（即时计算，不依赖 AI 分析完成）"""
    return await service.predict_book(current_user, personal_book_id)


@router.get(
    "/{personal_book_id}/chapters/{chapter_index}/prediction",
    response_model=ChapterPrediction,
)
async def get_chapter_prediction(
    personal_book_id: int,
    chapter_index: int,
    service: PersonalPredictionService = Depends(get_personal_prediction_service),
    current_user=Depends(get_current_user),
):
    """单章个性化预测（阅读器按章拉取）"""
    return await service.predict_chapter(current_user, personal_book_id, chapter_index)
