"""Harness Agent Runtime：不用 LangGraph 的显式 Agent 执行引擎。

这个运行时保留项目已有 Agent 和 Tool 体系，但把流程控制从 LangGraph 图
切换为 Harness 风格的顺序执行循环：规划、执行、写作、审查、必要时返工。
它为后续接入官方 Agent Framework Harness 留出统一适配面。
"""

import logging
import uuid
from typing import Any, Dict

from app.agents.planner import PlannerAgent
from app.agents.researcher import ResearcherAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.writer import WriterAgent
from app.models.state import ResearchState
from app.tools.router import ToolRouter
from app.workflow.events import emit
from app.workflow.nodes import formatter_node

logger = logging.getLogger(__name__)


class HarnessAgentRuntime:
    """显式控制多 Agent 执行循环的 Harness 运行时。"""

    def __init__(self, max_review_iterations: int = 3):
        self.max_review_iterations = max(1, max_review_iterations)
        self.router = ToolRouter()

    async def run(
        self,
        task: str,
        use_rag: bool = False,
        profile_id: str | None = None,
        task_id: str | None = None,
    ) -> ResearchState:
        """运行一次完整研究任务。"""
        from app.config import settings
        from app.services.workspace import WorkspaceManager

        resolved_task_id = task_id or f"task_{uuid.uuid4().hex[:12]}"
        ws = WorkspaceManager(root_dir=settings.WORKSPACE_ROOT)
        workspace_dir = await ws.ensure_workspace(resolved_task_id)
        workspace_files = [f["name"] for f in ws.list_files(resolved_task_id)]

        state = ResearchState(
            task=task,
            use_rag=use_rag,
            profile_id=profile_id,
            status="running",
            max_iterations=self.max_review_iterations,
            workspace_dir=workspace_dir,
            workspace_files=workspace_files,
        )
        try:
            await self._plan(state)
            await self._research(state)
            await self._write_and_review(state)
            await self._format(state)
            return state
        except Exception as exc:
            logger.exception("Harness runtime failed")
            state.status = "failed"
            state.errors.append(str(exc))
            emit("node_error", node="harness", error=str(exc))
            return state

    async def _plan(self, state: ResearchState) -> None:
        emit(
            "agent_status",
            agent="Harness Planner",
            status="running",
            detail="Planning research task with Harness runtime",
        )
        agent = PlannerAgent(use_rag=state.use_rag)
        updates = await agent.invoke(state)
        self._merge(state, updates)
        state.status = "running"
        emit(
            "agent_result",
            agent="Harness Planner",
            status="completed",
            plan_size=len(state.plan),
        )

    async def _research(self, state: ResearchState) -> None:
        agent = ResearcherAgent()
        while state.current_step < len(state.plan):
            current_task = state.plan[state.current_step]
            emit(
                "agent_status",
                agent="Harness Researcher",
                status="running",
                step=state.current_step,
                tool=current_task.tool,
                description=current_task.description,
            )
            updates = await agent.invoke(state, tools=self.router)
            self._merge(state, updates)
            emit(
                "agent_result",
                agent="Harness Researcher",
                status="completed",
                step=state.current_step,
                tool=current_task.tool,
            )

    async def _write_and_review(self, state: ResearchState) -> None:
        writer = WriterAgent()
        reviewer = ReviewerAgent()

        while True:
            emit(
                "agent_status",
                agent="Harness Writer",
                status="running",
                detail="Generating report draft",
                data_points=len(state.research_data),
            )
            self._merge(state, await writer.invoke(state))
            emit(
                "agent_result",
                agent="Harness Writer",
                status="completed",
                draft_length=len(state.report_draft),
            )

            emit(
                "agent_status",
                agent="Harness Reviewer",
                status="running",
                detail="Evaluating report quality",
                draft_length=len(state.report_draft),
            )
            self._merge(state, await reviewer.invoke(state))
            emit(
                "agent_result",
                agent="Harness Reviewer",
                status="completed",
                score=state.review_score,
                passed=state.review_score >= reviewer.passing_threshold,
            )

            if state.review_score >= reviewer.passing_threshold:
                return
            if state.iteration_count >= self.max_review_iterations:
                return

            emit(
                "agent_status",
                agent="Harness Runtime",
                status="iterating",
                detail="Review score below threshold, rewriting report",
                score=state.review_score,
                iteration=state.iteration_count,
            )

    async def _format(self, state: ResearchState) -> None:
        updates = await formatter_node(state)
        self._merge(state, updates)

    @staticmethod
    def _merge(state: ResearchState, updates: Dict[str, Any]) -> None:
        for key, value in (updates or {}).items():
            if hasattr(state, key):
                setattr(state, key, value)


async def run_research_harness(
    task: str,
    use_rag: bool = False,
    max_iterations: int = 3,
    profile_id: str | None = None,
    task_id: str | None = None,
) -> ResearchState:
    """使用 Harness Agent Runtime 运行研究任务。"""
    runtime = HarnessAgentRuntime(max_review_iterations=max_iterations)
    return await runtime.run(
        task=task,
        use_rag=use_rag,
        profile_id=profile_id,
        task_id=task_id,
    )
