"""Task management service — single source of truth for task lifecycle.

Consolidates task creation, execution, event streaming, and persistence
into one place. Replaces the duplicate logic that previously lived in
both main.py and the old research_service.py.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.database import TaskModel, TaskRepository
from app.services.direct_answer_service import DirectAnswerService
from app.services.query_router import QueryRoute, QueryRouter
from app.services.report_service import ReportService
from app.workflow.engine import run_research as run_workflow
from app.workflow.events import set_event_callback

logger = logging.getLogger(__name__)


class TaskInfo:
    """In-memory state for a single research task.

    Kept in memory for fast access; also persisted to SQLite via
    TaskRepository for durability across restarts.
    """

    def __init__(
        self,
        task_id: str,
        task: str,
        status: str = "pending",
        engine: Optional[str] = None,
    ):
        self.task_id = task_id
        self.task = task
        self.status = status
        self.engine = engine
        self.events: List[Dict[str, Any]] = []
        self.final_report: str = ""
        self.review_score: float = 0.0
        self.review_feedback: str = ""
        self.errors: List[str] = []
        self.token_usage: list = []
        self.created_at: str = datetime.now().isoformat()
        self.completed_at: Optional[str] = None
        self.event_queues: List[asyncio.Queue] = []
        self.event_seq: int = 0
        self.current_step: int = 0
        self.iteration_count: int = 0
        self.workspace_dir: str = ""
        self.workspace_files: List[str] = []
        self.route: str = "pending"


class TaskManager:
    """Orchestrates research task lifecycle: create, run, stream, persist."""

    def __init__(self):
        self._tasks: Dict[str, TaskInfo] = {}
        self._report_service = ReportService()
        self._query_router = QueryRouter()
        self._direct_answer_service = DirectAnswerService()

    # ------------------------------------------------------------------
    # Task CRUD
    # ------------------------------------------------------------------

    def create_task(
        self,
        task_text: str,
        task_id: Optional[str] = None,
        engine: Optional[str] = None,
    ) -> str:
        """Create a new task record and return its ID."""
        tid = task_id or f"task_{uuid.uuid4().hex[:12]}"
        self._tasks[tid] = TaskInfo(
            task_id=tid,
            task=task_text,
            status="pending",
            engine=self._normalize_engine(engine),
        )
        return tid

    def get_task(self, task_id: str) -> Optional[TaskInfo]:
        """Get task info by ID."""
        return self._tasks.get(task_id)

    def list_tasks(self) -> List[Dict[str, Any]]:
        """List all in-memory tasks with summary info."""
        results = []
        for task_id, info in self._tasks.items():
            results.append({
                "task_id": task_id,
                "task": info.task,
                "status": info.status,
                "created_at": info.created_at,
                "completed_at": info.completed_at or "",
                "summary": info.final_report[:200] if info.final_report else "",
                "engine": info.engine,
                "route": info.route,
            })
        return results

    def delete_task(self, task_id: str) -> bool:
        """Remove a task from memory and clean up its workspace directory."""
        removed = self._tasks.pop(task_id, None) is not None
        try:
            from app.config import settings
            from app.services.workspace import WorkspaceManager

            WorkspaceManager(root_dir=settings.WORKSPACE_ROOT).cleanup(task_id)
        except Exception as exc:
            logger.warning("Workspace cleanup failed for %s: %s", task_id, exc)
        return removed

    # ------------------------------------------------------------------
    # Event / SSE helpers
    # ------------------------------------------------------------------

    def push_event(self, task_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """Push an event to all SSE listeners for a task."""
        task_info = self._tasks.get(task_id)
        if not task_info:
            return

        task_info.event_seq += 1
        event_seq = task_info.event_seq
        event_data = {"type": event_type, "seq": event_seq, **data}
        task_info.events.append(event_data)
        try:
            asyncio.create_task(self._persist_event(task_id, event_type, data, event_seq))
        except RuntimeError:
            logger.debug("No running event loop; skip persisting event for %s", task_id)

        dead_queues: List[asyncio.Queue] = []
        for q in task_info.event_queues:
            try:
                q.put_nowait(event_data)
            except asyncio.QueueFull:
                dead_queues.append(q)
        for q in dead_queues:
            task_info.event_queues.remove(q)

    def register_sse_queue(self, task_id: str, queue: asyncio.Queue) -> None:
        """Register an SSE listener queue for a task."""
        task_info = self._tasks.get(task_id)
        if task_info:
            task_info.event_queues.append(queue)
            # Replay existing events
            for event in task_info.events:
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    break

    def unregister_sse_queue(self, task_id: str, queue: asyncio.Queue) -> None:
        """Remove an SSE listener queue."""
        task_info = self._tasks.get(task_id)
        if task_info and queue in task_info.event_queues:
            task_info.event_queues.remove(queue)

    # ------------------------------------------------------------------
    # Task recovery
    # ------------------------------------------------------------------

    async def save_checkpoint(self, task_id: str) -> None:
        """Persist current task state to the business database (best-effort).

        Called after each completed workflow node so task rows stay
        current across restarts.
        """
        task_info = self._tasks.get(task_id)
        if not task_info:
            return
        try:
            from app.models.database import _async_session_maker

            if _async_session_maker is None:
                return
            async with _async_session_maker() as session:
                repo = TaskRepository(session)
                task = await repo.get(task_id)
                if task:
                    task.status = task_info.status
                    task.report = task_info.final_report
                    task.review_score = task_info.review_score
                    task.review_feedback = task_info.review_feedback
                    task.errors = json.dumps(task_info.errors)
                    await repo.update(task)
                else:
                    # Create if not exists
                    from app.models.database import TaskModel
                    await repo.create(TaskModel(
                        id=task_id,
                        task_text=task_info.task,
                        status=task_info.status,
                        report=task_info.final_report,
                        review_score=task_info.review_score,
                        review_feedback=task_info.review_feedback,
                        errors=json.dumps(task_info.errors),
                    ))
        except Exception as exc:
            logger.warning("Failed to save checkpoint for %s: %s", task_id, exc)

    async def recover_interrupted_tasks(self) -> None:
        """Mark tasks left running after a restart as failed.

        Called on service startup so interrupted tasks surface as failed
        instead of appearing stuck forever.
        """
        try:
            from app.models.database import _async_session_maker

            if _async_session_maker is None:
                return
            async with _async_session_maker() as session:
                repo = TaskRepository(session)
                from sqlalchemy import select
                result = await session.execute(
                    select(TaskModel).where(TaskModel.status.in_(["pending", "running"]))
                )
                interrupted = list(result.scalars().all())
                for task in interrupted:
                    logger.info("Marking interrupted task %s as failed (restart)", task.id)
                    task.status = "failed"
                    task.errors = json.dumps(
                        ["任务因服务重启而中断"]
                    )
                    await repo.update(task)
        except Exception as exc:
            logger.warning("Failed to recover interrupted tasks: %s", exc)

    # ------------------------------------------------------------------
    # Background execution
    # ------------------------------------------------------------------

    async def start_research(
        self,
        task_text: str,
        max_iterations: int = 3,
        fmt: str = "markdown",
        use_rag: bool = False,
        profile_id: Optional[str] = None,
        engine: Optional[str] = None,
    ) -> str:
        """Create and launch a background research task.

        Returns the task_id immediately while research runs asynchronously.
        """
        selected_engine = self._normalize_engine(engine)
        task_id = self.create_task(task_text, engine=selected_engine)
        task_info = self._tasks[task_id]

        from app.config import settings
        from app.services.workspace import WorkspaceManager

        ws = WorkspaceManager(root_dir=settings.WORKSPACE_ROOT)
        task_info.workspace_dir = await ws.ensure_workspace(task_id)
        task_info.workspace_files = [f["name"] for f in ws.list_files(task_id)]

        # Persist to database
        try:
            from app.models.database import _async_session_maker

            if _async_session_maker is not None:
                async with _async_session_maker() as session:
                    repo = TaskRepository(session)
                    await repo.create(TaskModel(
                        id=task_id,
                        task_text=task_text,
                        status="pending",
                    ))
        except Exception as exc:
            logger.warning("Failed to persist task to database: %s", exc)

        # Launch background runner
        asyncio.create_task(
            self._run(task_id, task_text, max_iterations, fmt, use_rag, profile_id, selected_engine)
        )

        # Save initial checkpoint
        asyncio.create_task(self.save_checkpoint(task_id))

        return task_id

    async def start_prepared_task(
        self,
        task_id: str,
        max_iterations: int = 3,
        fmt: str = "markdown",
        use_rag: bool = False,
        profile_id: Optional[str] = None,
        engine: Optional[str] = None,
    ) -> str:
        """Start background research for an existing pre-created task.

        Same as start_research but reuses an existing task/workspace instead
        of creating a new one. Raises KeyError if the task does not exist;
        ValueError if the task has already started.
        """
        task_info = self._tasks.get(task_id)
        if not task_info:
            raise KeyError(f"task not found: {task_id}")

        # Transition pending → running atomically (no awaits above this point)
        # so two concurrent /start calls cannot both schedule _run for the
        # same task. _run flips status to "running" again at its start
        # (harmless).
        if task_info.status in ("running", "completed", "failed"):
            raise ValueError(f"任务已启动: {task_id}")
        task_info.status = "running"
        task_info.engine = self._normalize_engine(engine or task_info.engine)

        from app.config import settings
        from app.services.workspace import WorkspaceManager

        ws = WorkspaceManager(root_dir=settings.WORKSPACE_ROOT)
        task_info.workspace_dir = await ws.ensure_workspace(task_id)
        # Re-sync so any files uploaded after prepare are picked up.
        task_info.workspace_files = [f["name"] for f in ws.list_files(task_id)]

        # Persist to database (was intentionally NOT persisted at prepare time)
        try:
            from app.models.database import _async_session_maker

            if _async_session_maker is not None:
                async with _async_session_maker() as session:
                    repo = TaskRepository(session)
                    await repo.create(TaskModel(
                        id=task_id,
                        task_text=task_info.task,
                        status="pending",
                    ))
        except Exception as exc:
            logger.warning("Failed to persist task to database: %s", exc)

        asyncio.create_task(
            self._run(
                task_id,
                task_info.task,
                max_iterations,
                fmt,
                use_rag,
                profile_id,
                task_info.engine,
            )
        )
        asyncio.create_task(self.save_checkpoint(task_id))
        return task_id

    async def _run(
        self,
        task_id: str,
        task_text: str,
        max_iterations: int,
        fmt: str,
        use_rag: bool,
        profile_id: Optional[str] = None,
        engine: str = "langgraph",
    ) -> None:
        """Background runner: routes simple questions or executes the selected workflow."""
        task_info = self._tasks[task_id]
        task_info.status = "running"

        # Update database status
        await self._persist_status(task_id, "running")

        # Wire up event callback so workflow nodes emit events
        def _event_callback(event_type: str, data: Dict[str, Any]) -> None:
            self.push_event(task_id, event_type, data)

        set_event_callback(_event_callback)
        from app.utils.llm import set_usage_meter

        usage_meter: list = []
        set_usage_meter(usage_meter)

        try:
            self.push_event(task_id, "agent_status", {
                "agent": "System",
                "status": "running",
                "detail": "Starting research pipeline",
            })

            route = self._decide_route(task_text)
            task_info.route = route.route
            self.push_event(task_id, "agent_status", {
                "agent": "Router",
                "status": "completed",
                "detail": f"Route: {route.route}. {route.reason}",
            })

            if route.route == "direct_search":
                direct_result = await self._direct_answer_service.answer(task_text)
                report_text = direct_result["report"]
                sources = direct_result.get("sources", []) or []

                await self._stream_and_save_completion(
                    task_id=task_id,
                    task_text=task_text,
                    report_text=report_text,
                    fmt=fmt,
                    review_score=direct_result.get("review_score", 1.0),
                    review_feedback=direct_result.get("review_feedback", ""),
                    research_data=[],
                    sources=sources,
                    total_tokens=0,
                    summary="Direct search answer complete",
                )
                return

            self.push_event(task_id, "agent_status", {
                "agent": "Workflow",
                "status": "running",
                "detail": f"Running {engine} research pipeline",
            })

            final_state = await run_workflow(
                task_text,
                use_rag=use_rag,
                profile_id=profile_id,
                max_iterations=max_iterations,
                task_id=task_id,
                engine=engine,
            )

            # Extract results (supports both object and dict-like return)
            if hasattr(final_state, "status"):
                state_status = final_state.status
                state_errors = final_state.errors
                report_text = final_state.final_report
                review_score = final_state.review_score
                review_feedback = final_state.review_feedback
                research_data = getattr(final_state, "research_data", []) or []
                sources = getattr(final_state, "sources", []) or []
            else:
                state_status = final_state.get("status", "failed")
                state_errors = final_state.get("errors", [])
                report_text = final_state.get("final_report", "")
                review_score = final_state.get("review_score", 0.0)
                review_feedback = final_state.get("review_feedback", "")
                research_data = final_state.get("research_data", []) or []
                sources = final_state.get("sources", []) or []

            if state_status == "failed":
                raise ValueError(state_errors[-1] if state_errors else "Research workflow failed")

            # Validate citations and append a verification section
            try:
                from app.utils.citation_validator import (
                    extract_citations,
                    render_validation_section,
                    validate_citations,
                )

                checks = await validate_citations(extract_citations(report_text))
                report_text += render_validation_section(checks)
            except Exception as exc:
                logger.warning("Citation validation failed: %s", exc)

            # Claim-evidence grounding audit
            try:
                from app.utils.grounding import GroundingChecker, render_evidence_table

                grounding_checks = await GroundingChecker().check_report(report_text)
                report_text += render_evidence_table(grounding_checks)
            except Exception as exc:
                logger.warning("Grounding check failed: %s", exc)

            total_tokens = sum(u.get("total_tokens", 0) for u in usage_meter)
            await self._stream_and_save_completion(
                task_id=task_id,
                task_text=task_text,
                report_text=report_text,
                fmt=fmt,
                review_score=review_score,
                review_feedback=review_feedback,
                research_data=research_data,
                sources=sources,
                total_tokens=total_tokens,
                summary="Research complete",
            )

            # Trigger post-task evolution analysis (background, non-blocking)
            try:
                from app.services.evolution_service import analyze_task

                asyncio.create_task(analyze_task(task_id, final_state))
            except Exception as exc:
                logger.warning("Evolution analysis dispatch failed: %s", exc)

        except Exception as exc:
            logger.exception("Research task %s failed", task_id)
            task_info.status = "failed"
            task_info.errors.append(str(exc))
            task_info.completed_at = datetime.now().isoformat()

            await self._persist_status(task_id, "failed", error=str(exc))

            self.push_event(task_id, "error", {
                "message": str(exc),
                "detail": "An error occurred during research",
            })
        finally:
            set_event_callback(None)
            set_usage_meter(None)

    def _decide_route(self, task_text: str) -> QueryRoute:
        """Decide whether a question should use direct search or multi-agent workflow."""
        if not settings.QUERY_ROUTER_ENABLED:
            return QueryRoute(
                route="multi_agent",
                reason="QUERY_ROUTER_ENABLED=false，强制进入多 Agent 工作流",
            )
        return self._query_router.route(task_text)

    @staticmethod
    def _normalize_engine(engine: Optional[str]) -> str:
        """Normalize workflow engine name to a supported value."""
        selected = (engine or settings.WORKFLOW_ENGINE or "langgraph").strip().lower()
        return selected if selected in ("langgraph", "harness") else "langgraph"

    async def _stream_and_save_completion(
        self,
        task_id: str,
        task_text: str,
        report_text: str,
        fmt: str,
        review_score: float,
        review_feedback: str,
        research_data: Optional[list] = None,
        sources: Optional[list] = None,
        total_tokens: int = 0,
        summary: str = "Research complete",
    ) -> None:
        """Stream final report, save it, update memory state and persist completion."""
        task_info = self._tasks[task_id]

        chunk_size = 500
        for i in range(0, len(report_text), chunk_size):
            chunk = report_text[i: i + chunk_size]
            self.push_event(task_id, "report_chunk", {"chunk": chunk})
            await asyncio.sleep(0.02)

        try:
            await self._report_service.save_report(
                task_id=task_id,
                content=report_text,
                fmt=fmt,
                task_display=task_text,
                sources=sources or [{"title": task_text, "url": ""}],
                workspace_dir=task_info.workspace_dir,
            )
        except Exception as save_err:
            logger.warning("Failed to save report: %s", save_err)

        task_info.final_report = report_text
        task_info.review_score = review_score
        task_info.review_feedback = review_feedback
        task_info.token_usage = [{"total_tokens": total_tokens}] if total_tokens else []
        task_info.status = "completed"
        task_info.completed_at = datetime.now().isoformat()

        await self._persist_completion(
            task_id,
            report_text,
            review_score,
            review_feedback,
            research_data=research_data,
            sources=sources,
            total_tokens=total_tokens,
        )

        self.push_event(task_id, "completed", {
            "summary": summary,
            "score": review_score,
            "report": report_text,
        })

    # ------------------------------------------------------------------
    # Database persistence helpers
    # ------------------------------------------------------------------

    async def _persist_status(self, task_id: str, status: str, error: str = "") -> None:
        """Update task status in database (best-effort)."""
        try:
            from app.models.database import _async_session_maker

            if _async_session_maker is None:
                return
            async with _async_session_maker() as session:
                repo = TaskRepository(session)
                task = await repo.get(task_id)
                if task:
                    task.status = status
                    if error:
                        task.errors = json.dumps([error])
                    await repo.update(task)
        except Exception as exc:
            logger.warning("Failed to persist status for %s: %s", task_id, exc)

    async def _persist_event(
        self,
        task_id: str,
        event_type: str,
        data: Dict[str, Any],
        event_seq: int,
    ) -> None:
        """Persist one task event for later history playback."""
        try:
            from app.models.database import TaskEventRepository, _async_session_maker

            if _async_session_maker is None:
                return
            async with _async_session_maker() as session:
                repo = TaskEventRepository(session)
                await repo.add_event(task_id, event_type, data, event_seq=event_seq)
        except Exception as exc:
            logger.debug("Failed to persist event for %s: %s", task_id, exc)

    async def _persist_completion(
        self,
        task_id: str,
        report: str,
        score: float,
        feedback: str,
        research_data: Optional[list] = None,
        sources: Optional[list] = None,
        total_tokens: int = 0,
    ) -> None:
        """Persist completed task data (best-effort)."""
        try:
            from app.models.database import ReportModel, ReportRepository, _async_session_maker

            if _async_session_maker is None:
                return
            async with _async_session_maker() as session:
                # Update task
                repo = TaskRepository(session)
                task = await repo.get(task_id)
                if task:
                    task.status = "completed"
                    task.report = report
                    task.review_score = score
                    task.review_feedback = feedback
                    task.completed_at = datetime.now()
                    task.research_data = json.dumps(
                        research_data or [], ensure_ascii=False, default=str
                    )
                    task.sources = json.dumps(
                        sources or [], ensure_ascii=False, default=str
                    )
                    task.total_tokens = total_tokens
                    await repo.update(task)

                # Save report
                report_repo = ReportRepository(session)
                await report_repo.create(ReportModel(
                    id=f"rp_{uuid.uuid4().hex[:12]}",
                    task_id=task_id,
                    content=report,
                    format="markdown",
                ))
        except Exception as exc:
            logger.warning("Failed to persist completion for %s: %s", task_id, exc)
