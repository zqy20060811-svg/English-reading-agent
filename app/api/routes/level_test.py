from fastapi import APIRouter, Depends, HTTPException

from app.schemas.level_test import LevelTestPaperOut, LevelTestResultOut, LevelTestSubmit
from app.services.level_test_service import LevelTestService, get_level_test_service
from app.services.user_service import get_current_user

# 整个英语水平测试路由均需登录：自动校验 Bearer token
router = APIRouter(
    prefix="/level-test",
    tags=["英语水平测试"],
    dependencies=[Depends(get_current_user)],
)


@router.get("/questions", response_model=LevelTestPaperOut)
async def get_paper(current_user=Depends(get_current_user)):
    """获取整卷测试题（预设题库，不含答案与解析）"""
    return LevelTestService.get_paper()


@router.post("/submit", response_model=LevelTestResultOut)
async def submit(
    data: LevelTestSubmit,
    service: LevelTestService = Depends(get_level_test_service),
    current_user=Depends(get_current_user),
):
    """提交答案：自动评分 → CEFR 定级 → 能力分析 → 保存结果 → 返回推荐书目"""
    try:
        return await service.submit(current_user.id, data)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/result", response_model=LevelTestResultOut)
async def latest_result(
    service: LevelTestService = Depends(get_level_test_service),
    current_user=Depends(get_current_user),
):
    """获取当前用户最近一次测试结果（未测试过返回 404）"""
    result = await service.get_latest_result(current_user.id)
    if result is None:
        raise HTTPException(status_code=404, detail="尚未参加过英语水平测试")
    return result
