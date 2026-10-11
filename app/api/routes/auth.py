from fastapi import APIRouter, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.db.database import get_db
from app.schemas.user import TokenResponse, UserLoginRequest, UserOut, UserRegisterRequest
from app.services.user_service import UserService, get_current_user

router = APIRouter(prefix="/auth", tags=["认证"])
bearer_scheme = HTTPBearer()


@router.post("/register", response_model=UserOut, status_code=201)
async def register(req: UserRegisterRequest, db=Depends(get_db)):
    """注册新用户"""
    return await UserService(db).register(req)


@router.post("/login", response_model=TokenResponse)
async def login(req: UserLoginRequest, db=Depends(get_db)):
    """登录，返回 JWT access_token（token 同步存入 Redis 2 号库）"""
    token = await UserService(db).login(req)
    return TokenResponse(access_token=token)


@router.post("/logout")
async def logout(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db=Depends(get_db),
):
    """登出：删除 Redis 中的 token，令其立即失效"""
    await UserService(db).logout(credentials.credentials)
    return {"detail": "登出成功"}
