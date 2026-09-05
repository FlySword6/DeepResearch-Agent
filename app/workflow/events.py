"""Event publishing mechanism for workflow node execution.

Uses a task-local context variable so concurrent research tasks never
share callbacks (fixes cross-task SSE event contamination).
"""

import contextvars
import logging
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Type alias for event callbacks
# Signature: (event_type: str, data: dict) -> None
EventCallback = Callable[[str, Dict[str, Any]], None]

# Task-local active event callback. asyncio.create_task copies the current
# context into the new task; setting this inside a background task keeps
# events scoped to that task and its children.
_active_callback: "contextvars.ContextVar[Optional[EventCallback]]" = contextvars.ContextVar(
    "deep_research_event_callback", default=None
)


def set_event_callback(callback: Optional[EventCallback]) -> None:
    """Set or clear the event callback for the *current* task."""
    _active_callback.set(callback)


def emit(event_type: str, **data: Any) -> None:
    """Emit an event to the current task's callback (if any)."""
    callback = _active_callback.get()
    if callback is not None:
        try:
            callback(event_type, data)
        except Exception as exc:
            logger.warning("Event callback failed: %s", exc)


async def emit_node_event_before(node_name: str, detail: str = "") -> None:
    """Emit a standard 'before node execution' event."""
    emit(
        "agent_status",
        agent=node_name.capitalize(),
        status="running",
        detail=detail or f"Executing {node_name} node",
    )


async def emit_node_event_after(node_name: str, result: Any = None) -> None:
    """Emit a standard 'after node execution' event."""
    emit(
        "agent_result",
        agent=node_name.capitalize(),
        status="completed",
        detail=f"{node_name} node completed",
        result=str(result)[:500] if result else "",
    )
