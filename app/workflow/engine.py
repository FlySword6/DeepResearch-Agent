"""工作流引擎分发：支持 LangGraph 与 Harness 双引擎切换。"""

import logging
from typing import Optional

from app.config import settings
from app.models.state import ResearchState
from app.workflow.graph import run_research as run_langgraph_research

logger = logging.getLogger(__name__)


async def run_research(
    task: str,
    use_rag: bool = False,
    max_iterations: Optional[int] = None,
    profile_id: Optional[str] = None,
    task_id: Optional[str] = None,
    engine: Optional[str] = None,
) -> ResearchState:
    """按配置选择研究工作流引擎。"""
    selected = (engine or settings.WORKFLOW_ENGINE or "langgraph").strip().lower()

    if selected == "harness":
        from app.harness.runtime import run_research_harness

        logger.info("Running research with Harness Agent Runtime")
        return await run_research_harness(
            task=task,
            use_rag=use_rag,
            max_iterations=max_iterations or 3,
            profile_id=profile_id,
            task_id=task_id,
        )

    if selected != "langgraph":
        logger.warning("Unknown WORKFLOW_ENGINE='%s', falling back to LangGraph", selected)

    logger.info("Running research with LangGraph workflow")
    return await run_langgraph_research(
        task=task,
        use_rag=use_rag,
        max_iterations=max_iterations or 3,
        profile_id=profile_id,
        task_id=task_id,
    )
