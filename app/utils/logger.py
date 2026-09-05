"""DeepResearch-Agent 的结构化日志配置。

提供：
- 基于 contextvars 的 request_id 传播
- 生产环境可解析的 JSON 格式日志
- 开发环境更易读的纯文本日志
"""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import datetime, timezone

# request_id 上下文变量，会自动随异步任务传播。
request_id_var: ContextVar[str] = ContextVar("request_id", default="")
task_id_var: ContextVar[str] = ContextVar("task_id", default="")


def get_request_id() -> str:
    """从上下文中获取当前 request_id。"""
    return request_id_var.get()


def set_request_id(request_id: str) -> None:
    """把 request_id 写入当前上下文。"""
    request_id_var.set(request_id)


def get_task_id() -> str:
    """从上下文中获取当前 task_id。"""
    return task_id_var.get()


class StructuredFormatter(logging.Formatter):
    """当 LOG_FORMAT=json 时输出 JSON Lines 的日志格式化器。

    JSON 模式下，每一行日志都是可解析的 JSON 对象，包含 timestamp、
    level、logger、message 和上下文字段；本地开发时回退为易读文本格式。
    """

    def __init__(self):
        super().__init__()
        self._json_mode = False

    def format(self, record: logging.LogRecord) -> str:
        rid = get_request_id()
        tid = get_task_id()
        ts = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

        # 生产环境 JSON 模式。
        if self._json_mode:
            fields = {
                "timestamp": ts,
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if rid:
                fields["request_id"] = rid
            if tid:
                fields["task_id"] = tid
            if record.exc_info and record.exc_info[0]:
                fields["exception"] = self.formatException(record.exc_info)
            return json.dumps(fields, ensure_ascii=False)

        # 开发环境文本模式。
        parts = [
            ts,
            f"{record.levelname:<8}",
            f"{record.name}:{record.lineno}",
        ]
        if rid:
            parts.append(f"[req={rid[:8]}]")
        parts.append(record.getMessage())
        return " | ".join(parts)


def setup_logging(level: str = "INFO") -> None:
    """为应用配置结构化日志。

    它会设置统一日志格式，包含时间戳、日志级别、模块名和 request_id。
    读取 LOG_FORMAT 环境变量；设置为 "json" 时输出结构化 JSON。

    参数：
        level: 日志级别字符串，例如 DEBUG、INFO、WARNING、ERROR、CRITICAL。
    """
    import os

    formatter = StructuredFormatter()
    formatter._json_mode = os.environ.get("LOG_FORMAT", "").lower() == "json"

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    # 移除默认 handler，替换为项目统一 handler。
    for h in root_logger.handlers[:]:
        root_logger.removeHandler(h)
    root_logger.addHandler(handler)
