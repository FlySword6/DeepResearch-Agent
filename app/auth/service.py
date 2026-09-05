"""认证服务：注册、登录和 JWT 管理。"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt as _bcrypt
from jose import JWTError, jwt

from app.config import settings

logger = logging.getLogger(__name__)

# JWT 配置
SECRET_KEY = getattr(settings, "JWT_SECRET", "dev-secret-change-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30
REFRESH_TOKEN_EXPIRE_DAYS = 7


def hash_password(password: str) -> str:
    """使用 bcrypt 对明文密码做哈希。"""
    return _bcrypt.hashpw(password.encode("utf-8")[:72], _bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """校验明文密码是否匹配 bcrypt 哈希。"""
    return _bcrypt.checkpw(plain_password.encode("utf-8")[:72], hashed_password.encode("utf-8"))


def create_access_token(user_id: str, username: str) -> str:
    """创建签名后的 JWT access token。"""
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {
        "sub": user_id,
        "username": username,
        "exp": expire,
        "type": "access",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """创建签名后的 JWT refresh token，有效期更长。"""
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """解码并校验 JWT，成功时返回 payload，失败时返回 None。"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError as exc:
        logger.debug("Token decode failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# 内存用户存储，简化实现；生产环境应替换为数据库表
# ---------------------------------------------------------------------------

_users: dict = {}  # 用户名 -> {id, username, password_hash, created_at}


def _in_memory_register(username: str, password: str) -> Optional[dict]:
    if username in _users:
        return None
    user = {
        "id": f"user_{uuid.uuid4().hex[:12]}",
        "username": username,
        "password_hash": hash_password(password),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _users[username] = user
    return {
        "id": user["id"],
        "username": user["username"],
        "created_at": user["created_at"],
    }


def _in_memory_login(username: str, password: str) -> Optional[dict]:
    user = _users.get(username)
    if not user:
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return {
        "id": user["id"],
        "username": user["username"],
        "created_at": user["created_at"],
    }


# ---------------------------------------------------------------------------
# 对外 API
# ---------------------------------------------------------------------------


async def register_user(username: str, password: str) -> Optional[dict]:
    """注册新用户；用户名已存在时返回 None。"""
    return _in_memory_register(username, password)


async def authenticate_user(username: str, password: str) -> Optional[dict]:
    """按用户名和密码认证用户；失败时返回 None。"""
    return _in_memory_login(username, password)
