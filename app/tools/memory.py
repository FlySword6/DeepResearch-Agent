"""MemoryTool — delegates to SessionMemory and KnowledgeMemory.

Provides a unified tool interface for all memory operations:
  - session_save    – persist a ResearchState (24h TTL)
  - session_load    – load a previously saved state
  - session_list    – list active session IDs
  - knowledge_save  – store a research report for cross-task reuse
  - knowledge_query – find reports similar to a query
  - knowledge_list  – list recent reports
"""

import logging
from typing import Any, Dict, List, Optional

from app.memory.session_memory import SessionMemory
from app.memory.knowledge_memory import KnowledgeMemory
from app.models.state import ResearchState
from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MEMORY_PARAMETERS = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": [
                "session_save",
                "session_load",
                "session_list",
                "knowledge_save",
                "knowledge_query",
                "knowledge_list",
            ],
            "description": (
                "Operation to perform:\n"
                "  session_save    – persist a ResearchState\n"
                "  session_load    – load a previously saved state\n"
                "  session_list    – list active session IDs\n"
                "  knowledge_save  – store a research report\n"
                "  knowledge_query – find reports similar to a query\n"
                "  knowledge_list  – list recent reports"
            ),
        },
        "task_id": {
            "type": "string",
            "description": "Task ID (required for session_save, session_load)",
        },
        "state": {
            "description": "ResearchState dict (required for session_save)",
        },
        "task": {
            "type": "string",
            "description": "Research task/question (required for knowledge_save)",
        },
        "report": {
            "type": "string",
            "description": "Report text (required for knowledge_save)",
        },
        "tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Optional tags for knowledge_save",
        },
        "query": {
            "type": "string",
            "description": "Search query (required for knowledge_query)",
        },
        "k": {
            "type": "integer",
            "description": "Max results for knowledge_query (default 3)",
        },
        "limit": {
            "type": "integer",
            "description": "Max results for knowledge_list (default 20)",
        },
    },
    "required": ["action"],
}


class MemoryTool(BaseTool):
    """Unified memory tool backed by SessionMemory and KnowledgeMemory."""

    name = "memory"
    description = "Delegates to SessionMemory and KnowledgeMemory for state persistence and cross-task knowledge reuse"
    parameters = MEMORY_PARAMETERS

    def __init__(self) -> None:
        self._session_memory = SessionMemory()
        self._knowledge_memory = KnowledgeMemory()

    async def execute(
        self,
        action: str,
        task_id: Optional[str] = None,
        state: Optional[Dict[str, Any]] = None,
        task: Optional[str] = None,
        report: Optional[str] = None,
        tags: Optional[List[str]] = None,
        query: Optional[str] = None,
        k: Optional[int] = None,
        limit: Optional[int] = None,
        **_kwargs: Any,
    ) -> ToolResult:
        """Dispatch to the requested action."""
        normalized = action.strip().lower()

        # ---- Session memory actions ------------------------------------
        if normalized == "session_save":
            return await self._session_save(task_id, state)
        elif normalized == "session_load":
            return await self._session_load(task_id)
        elif normalized == "session_list":
            return await self._session_list()

        # ---- Knowledge memory actions -----------------------------------
        elif normalized == "knowledge_save":
            return await self._knowledge_save(task, report, tags)
        elif normalized == "knowledge_query":
            return await self._knowledge_query(query, k)
        elif normalized == "knowledge_list":
            return await self._knowledge_list(limit)
        else:
            return ToolResult(
                success=False,
                error=(
                    f"Unknown action '{action}'. "
                    f"Use session_save, session_load, session_list, "
                    f"knowledge_save, knowledge_query, or knowledge_list."
                ),
            )

    # ------------------------------------------------------------------
    # Session memory implementations
    # ------------------------------------------------------------------

    async def _session_save(
        self, task_id: Optional[str], state_data: Optional[Dict[str, Any]]
    ) -> ToolResult:
        if not task_id:
            return ToolResult(success=False, error="'task_id' is required for session_save.")
        if not state_data:
            return ToolResult(success=False, error="'state' is required for session_save.")

        try:
            research_state = ResearchState(**state_data)
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Invalid ResearchState data: {exc}",
            )

        try:
            await self._session_memory.save_state(task_id, research_state)
            return ToolResult(
                success=True,
                data={"task_id": task_id, "stored": True},
            )
        except Exception as exc:
            logger.exception("session_save failed")
            return ToolResult(success=False, error=str(exc))

    async def _session_load(self, task_id: Optional[str]) -> ToolResult:
        if not task_id:
            return ToolResult(success=False, error="'task_id' is required for session_load.")

        try:
            state = await self._session_memory.load_state(task_id)
            if state is None:
                return ToolResult(
                    success=False,
                    error=f"Session '{task_id}' not found or expired.",
                )
            return ToolResult(
                success=True,
                data={"task_id": task_id, "state": state.model_dump()},
            )
        except Exception as exc:
            logger.exception("session_load failed")
            return ToolResult(success=False, error=str(exc))

    async def _session_list(self) -> ToolResult:
        try:
            sessions = await self._session_memory.list_sessions()
            return ToolResult(
                success=True,
                data={"sessions": sessions, "count": len(sessions)},
            )
        except Exception as exc:
            logger.exception("session_list failed")
            return ToolResult(success=False, error=str(exc))

    # ------------------------------------------------------------------
    # Knowledge memory implementations
    # ------------------------------------------------------------------

    async def _knowledge_save(
        self,
        task: Optional[str],
        report: Optional[str],
        tags: Optional[List[str]],
    ) -> ToolResult:
        if not task:
            return ToolResult(success=False, error="'task' is required for knowledge_save.")
        if not report:
            return ToolResult(success=False, error="'report' is required for knowledge_save.")

        try:
            report_id = await self._knowledge_memory.save_report(
                task=task, report=report, tags=tags or []
            )
            return ToolResult(
                success=True,
                data={"report_id": report_id, "stored": True},
            )
        except Exception as exc:
            logger.exception("knowledge_save failed")
            return ToolResult(success=False, error=str(exc))

    async def _knowledge_query(
        self, query: Optional[str], k: Optional[int]
    ) -> ToolResult:
        if not query:
            return ToolResult(success=False, error="'query' is required for knowledge_query.")

        try:
            results = await self._knowledge_memory.query_similar(
                query=query, k=k or 3
            )
            return ToolResult(
                success=True,
                data={"results": results, "count": len(results)},
            )
        except Exception as exc:
            logger.exception("knowledge_query failed")
            return ToolResult(success=False, error=str(exc))

    async def _knowledge_list(self, limit: Optional[int]) -> ToolResult:
        try:
            reports = await self._knowledge_memory.list_reports(limit=limit or 20)
            return ToolResult(
                success=True,
                data={"reports": reports, "count": len(reports)},
            )
        except Exception as exc:
            logger.exception("knowledge_list failed")
            return ToolResult(success=False, error=str(exc))
