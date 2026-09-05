"""会话记忆：保存当前任务上下文和执行状态。

生产环境可使用 Redis；本地开发时回退到内存字典。
"""

import json
import logging
import time
from typing import Dict, List, Optional

from app.models.state import ResearchState

logger = logging.getLogger(__name__)


class SessionMemory:
    """保存当前研究任务的上下文和执行状态。

    这里使用内存字典模拟 Redis 行为；如果安装 fakeredis，
    会标记为具备 Redis 兼容 API 的开发模式。
    """

    def __init__(self, redis_url: str = "redis://localhost:6379"):
        self._redis_url = redis_url
        self._redis = None  # 生产环境可替换为 aioredis/fakeredis。
        self._store: Dict[str, str] = {}  # task_id -> JSON 序列化后的状态
        self._ttl: Dict[str, float] = {}  # task_id -> 过期时间戳

        # 尝试探测 fakeredis，让开发行为更接近 Redis。
        self._use_fakeredis = False
        try:
            import fakeredis.aioredis  # noqa: F401

            # 真实部署可在这里初始化 fakeredis/Redis。
            # 为了简单可靠，当前仍使用内存字典，只记录 fakeredis 可用。
            self._use_fakeredis = True
            logger.info("fakeredis available — using in-memory store (Redis-compatible API ready)")
        except ImportError:
            logger.info("fakeredis not installed — using pure in-memory dict store")

    # ------------------------------------------------------------------
    # 对外 API
    # ------------------------------------------------------------------

    async def save_state(self, task_id: str, state: ResearchState) -> None:
        """保存 ResearchState，并设置 24 小时 TTL。

        参数：
            task_id: 研究任务唯一 ID。
            state: 需要持久化的 ResearchState。
        """
        serialized = state.model_dump_json()
        self._store[task_id] = serialized
        self._ttl[task_id] = time.time() + 86400  # 24 小时
        logger.debug("Saved state for task '%s' (expires in 24h)", task_id)

    async def load_state(self, task_id: str) -> Optional[ResearchState]:
        """加载之前保存过的 ResearchState。

        如果 key 不存在或已过期，则返回 None。

        参数：
            task_id: 研究任务唯一 ID。

        返回：
            反序列化后的 ResearchState，或 None。
        """
        if self._is_expired(task_id):
            if task_id in self._store:
                logger.info("State for task '%s' has expired — cleaning up", task_id)
                await self.delete_state(task_id)
            return None

        raw = self._store.get(task_id)
        if raw is None:
            return None

        try:
            data = json.loads(raw)
            return ResearchState(**data)
        except (json.JSONDecodeError, TypeError) as exc:
            logger.error("Failed to deserialize state for task '%s': %s", task_id, exc)
            return None

    async def delete_state(self, task_id: str) -> None:
        """删除一条任务状态。

        参数：
            task_id: 研究任务唯一 ID。
        """
        self._store.pop(task_id, None)
        self._ttl.pop(task_id, None)
        logger.debug("Deleted state for task '%s'", task_id)

    async def list_sessions(self) -> List[str]:
        """列出活跃且未过期的 session ID。

        返回：
            排序后的活跃任务 ID 列表。
        """
        active = [tid for tid in self._store if not self._is_expired(tid)]
        return sorted(active)

    # ------------------------------------------------------------------
    # 内部辅助函数
    # ------------------------------------------------------------------

    def _is_expired(self, key: str) -> bool:
        """检查 key 是否已过期。

        参数：
            key: 需要检查的任务 ID。

        返回：
            TTL 已到期或没有设置 TTL 时返回 True。
        """
        expiry = self._ttl.get(key)
        if expiry is None:
            return True  # 没有 TTL 时视为已过期或不存在。
        return time.time() > expiry

    def __len__(self) -> int:
        """返回已存储 session 数量，主要方便测试。"""
        return len(self._store)

    def __contains__(self, task_id: str) -> bool:
        """检查任务 ID 是否存在且未过期。"""
        return task_id in self._store and not self._is_expired(task_id)
