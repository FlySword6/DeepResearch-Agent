"""研究编排服务：管理任务生命周期和 SSE 事件。"""

import asyncio
import logging
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.config import settings
from app.models.state import ResearchState
from app.services.report_service import ReportService
from app.workflow.engine import run_research as run_workflow
from app.workflow.events import emit_node_event_before, emit_node_event_after, set_event_callback

logger = logging.getLogger(__name__)


class ResearchService:
    """编排研究任务执行，并维护生命周期状态。

    每个任务都会在内存中保存 asyncio task、ResearchState 和事件队列，
    用于支持启动、状态查询、事件流和取消等操作。
    """

    def __init__(self):
        self._tasks: Dict[str, asyncio.Task] = {}
        self._states: Dict[str, ResearchState] = {}
        self._events: Dict[str, asyncio.Queue] = {}
        self._report_service = ReportService()

    async def start_research(
        self, task: str, task_id: Optional[str] = None, options: Optional[Dict[str, Any]] = None
    ) -> str:
        """在后台启动研究任务。

        参数：
            task: 研究主题或问题。
            task_id: 可选任务 ID；不传时自动生成。
            options: 可选配置，例如 "max_iterations"、"format"。

        返回：
            用于状态查询或 SSE 流的 task_id。
        """
        if task_id is None:
            task_id = f"task_{uuid.uuid4().hex[:12]}"

        opts = options or {}
        max_iterations = opts.get("max_iterations", 3)
        fmt = opts.get("format", "markdown")
        use_rag = bool(opts.get("use_rag", False))

        # 初始化任务状态。
        initial_state = ResearchState(
            task=task,
            status="pending",
            use_rag=use_rag,
            max_iterations=max_iterations,
        )
        self._states[task_id] = initial_state
        self._events[task_id] = asyncio.Queue(maxsize=500)

        # 启动后台 asyncio 任务。
        bg_task = asyncio.create_task(
            self._run(
                task_id=task_id,
                task_text=task,
                max_iterations=max_iterations,
                fmt=fmt,
                use_rag=use_rag,
            )
        )
        self._tasks[task_id] = bg_task

        return task_id

    async def get_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        """获取研究任务的当前状态。

        参数：
            task_id: 任务 ID。

        返回：
            状态信息字典；任务不存在时返回 None。
        """
        state = self._states.get(task_id)
        if state is None:
            return None

        bg_task = self._tasks.get(task_id)
        done = bg_task.done() if bg_task else True

        return {
            "task_id": task_id,
            "status": state.status,
            "current_step": state.current_step,
            "total_steps": max(len(state.plan), 1),
            "progress": 1.0 if state.status == "completed" else 0.5 if state.status == "running" else 0.0,
            "errors": state.errors,
            "completed": done,
        }

    def get_events_queue(self, task_id: str) -> Optional[asyncio.Queue]:
        """获取任务对应的 SSE 事件队列。

        参数：
            task_id: 任务 ID。

        返回：
            用于 SSE 事件的 asyncio.Queue；不存在时返回 None。
        """
        return self._events.get(task_id)

    async def cancel_task(self, task_id: str) -> bool:
        """取消正在运行的任务。

        参数：
            task_id: 任务 ID。

        返回：
            成功取消时返回 True；未找到或已完成时返回 False。
        """
        bg_task = self._tasks.get(task_id)
        if bg_task is None or bg_task.done():
            return False

        bg_task.cancel()
        state = self._states.get(task_id)
        if state is not None:
            state.status = "failed"
            state.errors.append("Task cancelled by user")
            state.completed_at = datetime.now().isoformat()

        await self._push_event(task_id, "error", {"message": "Task cancelled by user"})
        return True

    def get_state(self, task_id: str) -> Optional[ResearchState]:
        """获取任务的 ResearchState。

        参数：
            task_id: 任务 ID。

        返回：
            ResearchState；不存在时返回 None。
        """
        return self._states.get(task_id)

    def list_tasks(self) -> List[Dict[str, Any]]:
        """列出所有已跟踪任务及基础状态信息。

        返回：
            包含 task_id、status、created_at 等字段的字典列表。
        """
        results = []
        for task_id, state in self._states.items():
            results.append({
                "task_id": task_id,
                "status": state.status,
                "task": state.task,
                "created_at": "",  # ResearchState 当前未记录创建时间。
                "completed_at": state.completed_at or "",
                "summary": state.final_report[:200] if state.final_report else "",
            })
        return results

    # ------------------------------------------------------------------
    # 内部辅助函数
    # ------------------------------------------------------------------

    async def _run(
        self, task_id: str, task_text: str, max_iterations: int, fmt: str, use_rag: bool
    ) -> None:
        """单个研究任务的后台 runner。

        它负责设置事件回调、运行工作流，并发布生命周期事件。
        """
        state = self._states[task_id]
        state.status = "running"

        # 创建局部回调，把节点事件推送到当前任务的事件队列。
        def _event_callback(event_type: str, data: Dict[str, Any]) -> None:
            # 后台调度：把推送协程交给事件循环执行。
            asyncio.create_task(self._push_event(task_id, event_type, data))

        # 注册回调，使工作流节点可以 emit 事件。
        set_event_callback(_event_callback)

        try:
            # 初始状态事件。
            await self._push_event(task_id, "agent_status", {
                "agent": "System",
                "status": "running",
                "detail": "Starting research pipeline",
            })

            # 发送 planner 阶段事件。
            await emit_node_event_before("planner", "Decomposing research task into subtasks")

            # 根据配置运行 LangGraph 或 Harness 工作流。
            final_state = await run_workflow(
                task_text,
                use_rag=use_rag,
                max_iterations=max_iterations,
            )

            if final_state.status == "failed":
                err_msg = final_state.errors[-1] if final_state.errors else "Research workflow failed"
                raise ValueError(err_msg)

            report_text = final_state.final_report

            # 用工作流输出更新内存状态。
            state.plan = final_state.plan
            state.current_step = final_state.current_step
            state.research_data = final_state.research_data
            state.report_draft = final_state.report_draft
            state.review_score = final_state.review_score
            state.review_feedback = final_state.review_feedback
            state.final_report = final_state.final_report
            state.iteration_count = final_state.iteration_count
            state.knowledge_report_id = final_state.knowledge_report_id

            # 分块推送报告，供前端流式展示。
            chunk_size = 500
            for i in range(0, len(report_text), chunk_size):
                chunk = report_text[i : i + chunk_size]
                await self._push_event(task_id, "report_chunk", {"chunk": chunk})
                await asyncio.sleep(0.02)

            # 发送 reviewer 阶段完成事件。
            await emit_node_event_after("reviewer")

            # 通过 ReportService 保存报告。
            try:
                await self._report_service.save_report(
                    task_id=task_id,
                    content=report_text,
                    fmt=fmt,
                    sources=[{"title": "Research Report", "url": ""}],
                )
            except Exception as save_err:
                logger.warning("Failed to save report: %s", save_err)

            # 标记任务完成。
            state.status = "completed"
            state.completed_at = datetime.now().isoformat()

            await self._push_event(task_id, "completed", {
                "summary": "Research complete",
                "score": final_state.review_score,
                "report": report_text,
            })

        except asyncio.CancelledError:
            logger.info("Research task %s was cancelled", task_id)
            state.status = "failed"
            state.completed_at = datetime.now().isoformat()
            if "Cancelled" not in "".join(state.errors):
                state.errors.append("Task cancelled")

        except Exception as exc:
            logger.exception("Research task %s failed", task_id)
            state.status = "failed"
            state.completed_at = datetime.now().isoformat()
            state.errors.append(str(exc))

            await self._push_event(task_id, "error", {
                "message": str(exc),
                "detail": "An error occurred during research",
            })

        finally:
            # 清空事件回调，避免影响后续任务。
            set_event_callback(None)

    async def _push_event(self, task_id: str, event_type: str, data: Dict[str, Any]) -> None:
        """把事件写入任务的 SSE 队列。"""
        queue = self._events.get(task_id)
        if queue is None:
            return

        event_data = {"type": event_type, **data}
        try:
            queue.put_nowait(event_data)
        except asyncio.QueueFull:
            logger.warning("Event queue full for task %s, dropping event %s", task_id, event_type)
