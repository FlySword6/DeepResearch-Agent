"""认证保护路由使用的 FastAPI 依赖。"""

import logging
from typing import Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.service import decode_token

logger = logging.getLogger(__name__)

# Swagger UI 使用的 Bearer 令牌方案。
bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> dict:
    """依赖函数：从 JWT 中提取并校验当前用户。

    认证成功时返回包含 'id'、'username' 的字典；
    token 缺失或无效时抛出 401。
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "id": payload.get("sub", ""),
        "username": payload.get("username", ""),
    }


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> Optional[dict]:
    """可选认证依赖：有 token 时提取用户，没有 token 时返回 None。"""
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials)
    if payload is None:
        return None
    return {
        "id": payload.get("sub", ""),
        "username": payload.get("username", ""),
    }
