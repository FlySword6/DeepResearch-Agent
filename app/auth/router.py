"""认证 API 路由：注册、登录和刷新 token。"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import get_current_user
from app.auth.schemas import TokenResponse, UserLogin, UserRegister, UserResponse
from app.auth.service import (
    authenticate_user,
    create_access_token,
    create_refresh_token,
    decode_token,
    register_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=UserResponse)
async def register(body: UserRegister):
    """注册新的用户账号。"""
    user = await register_user(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=409, detail="Username already taken")
    return UserResponse(**user)


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin):
    """认证用户并返回 JWT 令牌。"""
    user = await authenticate_user(body.username, body.password)
    if user is None:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    access_token = create_access_token(user["id"], user["username"])
    refresh_token = create_refresh_token(user["id"])

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: dict):
    """使用刷新令牌换取新的访问令牌和刷新令牌。"""
    refresh_token = body.get("refresh_token", "")
    payload = decode_token(refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    user_id = payload.get("sub", "")
    # 刷新令牌中不一定保存 username，这里优先从 payload 取，取不到则用 user_id。
    username = payload.get("username", user_id)

    new_access = create_access_token(user_id, username)
    new_refresh = create_refresh_token(user_id)

    return TokenResponse(access_token=new_access, refresh_token=new_refresh)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: dict = Depends(get_current_user)):
    """获取当前已认证用户信息。"""
    return UserResponse(
        id=current_user["id"],
        username=current_user["username"],
        created_at="",
    )
