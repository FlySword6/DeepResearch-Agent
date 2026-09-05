"""Current-date hint injected into agent prompts."""

from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))


def today_hint() -> str:
    """Return e.g. '今天是 2026-08-09（中国标准时间，UTC+8）'."""
    return datetime.now(CST).strftime("今天是 %Y-%m-%d（中国标准时间，UTC+8）")
