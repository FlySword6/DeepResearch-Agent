"""Optional Langfuse observability. No-op unless LANGFUSE_ENABLED=true."""

import logging
from typing import Any

logger = logging.getLogger(__name__)

_tracer: Any = None


def get_tracer():
    """Return a configured Langfuse client, or None when disabled."""
    global _tracer
    if _tracer is not None:
        return _tracer
    try:
        from app.config import settings

        if not settings.LANGFUSE_ENABLED:
            return None
        from langfuse import Langfuse

        _tracer = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_HOST,
        )
    except Exception as exc:
        logger.warning("Langfuse unavailable: %s", exc)
        _tracer = None
    return _tracer
