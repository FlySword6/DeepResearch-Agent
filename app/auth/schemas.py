"""用户注册和登录使用的认证模型。"""
from typing import Optional
from pydantic import BaseModel, Field


class UserRegister(BaseModel):
    """用户注册请求体。"""
    username: str = Field(..., min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_]+$")
    password: str = Field(..., min_length=6, max_length=128)


class UserLogin(BaseModel):
    """用户登录请求体。"""
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    """JWT token 响应。"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = 1800


class UserResponse(BaseModel):
    """对外返回的用户信息，不包含密码。"""
    id: str
    username: str
    created_at: str = ""
