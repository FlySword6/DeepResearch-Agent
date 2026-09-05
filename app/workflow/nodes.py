"""Workflow node functions for the LangGraph research pipeline."""

import asyncio
import logging
from typing import Any, Dict

from app.agents.planner import PlannerAgent
from app.agents.researcher import ResearcherAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.writer import WriterAgent
from app.memory.knowledge_memory import KnowledgeMemory
from app.models.state import ResearchState
from app.tools.router import ToolRouter
from app.workflow.events import emit

logger = logging.getLogger(__name__)

# Module-level singletons
_router: ToolRouter = None  # type: ignore[assignment]
_knowledge_memory: KnowledgeMemory = None  # type: ignore[assignment]


def _get_router() -> ToolRouter:
    global _router
    if _router is None:
        _router = ToolRouter()
    return _router


def _get_knowledge_memory() -> KnowledgeMemory:
    global _knowledge_memory
    if _knowledge_memory is None:
        _knowledge_memory = KnowledgeMemory()
    return _knowledge_memory


def router_decision(state: ResearchState) -> str:
    """
    Decide the next node to route to based on current state.

    Called by the conditional edge function in graph.py.
    Returns the name of the next node or 'END'.
    """
    if state.status == "failed":
        return "END"

    if not state.plan or len(state.plan) == 0:
        return "planner"

    if state.current_step < len(state.plan):
        return "researcher"

    if not state.report_draft:
        return "writer"

    # Max iterations reached — force to formatter regardless of score
    if state.iteration_count >= state.max_iterations:
        return "formatter"

    # If this is the first review and score is very low, iterate with writer
    if state.iteration_count < 2 and state.review_score < 0.5:
        return "writer"

    # Score meets threshold, proceed to formatter
    if state.review_score >= 0.5:
        return "formatter"

    # Otherwise iterate with writer
    return "writer"


async def planner_node(state: ResearchState) -> Dict[str, Any]:
    emit("agent_status", agent="Planner", status="running",
         detail="Decomposing research task into subtasks")

    # Determine if RAG is enabled from state/context
    use_rag = getattr(state, 'use_rag', False)

    try:
        from app.services.profile_service import get_agent_model

        agent = PlannerAgent(
            use_rag=use_rag,
            model_name=await get_agent_model("planner", getattr(state, "profile_id", None)),
        )
        result = await agent.invoke(state)

        if result.get("plan") and len(result["plan"]) > 0:
            updates: Dict[str, Any] = {
                "plan": result["plan"],
                "status": "running",
            }
            if result.get("perspectives"):
                updates["perspectives"] = result["perspectives"]
            if result.get("errors"):
                updates["errors"] = state.errors + result["errors"]

            emit("agent_result", agent="Planner", status="completed",
                 plan_size=len(result["plan"]))
            return updates
    except Exception as e:
        logger.warning(f"Planner LLM call failed, using fallback: {e}")
        emit("node_error", node="planner", error=str(e))

    # Fallback: generate a basic plan without LLM
    from app.models.state import SubTask

    fallback_plan = [
        SubTask(id="background", description=f"Research background of: {state.task}", tool="search"),
        SubTask(id="deep-dive", description=f"Deep dive into key aspects of: {state.task}", tool="browse"),
        SubTask(id="synthesis", description=f"Synthesize findings about: {state.task}", tool="analyze"),
    ]

    emit("agent_result", agent="Planner", status="fallback",
         plan_size=len(fallback_plan))
    return {
        "plan": fallback_plan,
        "status": "running",
    }


async def executor_node(state: ResearchState) -> Dict[str, Any]:
    """Execute up to RESEARCH_PARALLELISM remaining subtasks concurrently."""
    if state.current_step >= len(state.plan):
        emit("node_error", node="executor", error="current_step beyond plan length")
        return {"current_step": state.current_step}

    from app.config import settings

    router = _get_router()
    parallelism = max(
        1, min(settings.RESEARCH_PARALLELISM, len(state.plan) - state.current_step)
    )
    steps = list(range(state.current_step, state.current_step + parallelism))

    try:
        from app.services.profile_service import get_agent_model

        agent = ResearcherAgent(
            model_name=await get_agent_model("researcher", getattr(state, "profile_id", None))
        )
        emit(
            "agent_status",
            agent="Researcher",
            status="running",
            step=state.current_step,
            count=parallelism,
        )

        results = await asyncio.gather(
            *(agent.execute_step(state, i, router) for i in steps),
            return_exceptions=True,
        )

        entries: list = []
        new_sources: list = []
        for i, r in zip(steps, results):
            if isinstance(r, Exception):
                entries.append({
                    "step": i,
                    "task_id": state.plan[i].id,
                    "description": state.plan[i].description,
                    "tool": state.plan[i].tool,
                    "raw_result": f"Error: {r}",
                    "summary": f"子任务执行失败: {r}",
                })
            else:
                entry, srcs = r
                if entry:
                    entries.append(entry)
                new_sources.extend(srcs)

        emit("agent_result", agent="Researcher", status="completed", steps=len(entries))
        return {
            "research_data": list(state.research_data) + entries,
            "sources": list(state.sources) + new_sources,
            "current_step": state.current_step + len(entries),
        }
    except Exception as exc:
        logger.exception("Executor node failed for steps %s", steps)
        emit("node_error", node="executor", step=state.current_step, error=str(exc))
        return {
            "errors": state.errors + [str(exc)],
            "current_step": state.current_step,
        }


async def writer_node(state: ResearchState) -> Dict[str, Any]:
    """
    Writer node that generates a report draft from research data using WriterAgent.
    """
    emit("agent_status", agent="Writer", status="running",
         detail="Generating report from research data",
         data_points=len(state.research_data))
    try:
        from app.services.profile_service import get_agent_model

        agent = WriterAgent(
            model_name=await get_agent_model("writer", getattr(state, "profile_id", None))
        )
        result = await agent.invoke(state)
        draft = result.get("report_draft", "")
        emit("agent_result", agent="Writer", status="completed",
             draft_length=len(draft))
        return {"report_draft": draft}
    except Exception as e:
        logger.warning(f"Writer node LLM call failed, using fallback: {e}")
        emit("node_error", node="writer", error=str(e))

    # Fallback: use WriterAgent's built-in fallback
    agent = WriterAgent()
    draft = agent._fallback_report(state)

    emit("agent_result", agent="Writer", status="fallback",
         draft_length=len(draft))
    return {"report_draft": draft}


async def reviewer_node(state: ResearchState) -> Dict[str, Any]:
    """
    Reviewer node that evaluates the report draft quality using ReviewerAgent.
    """
    emit("agent_status", agent="Reviewer", status="running",
         detail="Evaluating report quality",
         draft_length=len(state.report_draft) if state.report_draft else 0)
    try:
        from app.services.profile_service import get_agent_model

        agent = ReviewerAgent(
            model_name=await get_agent_model("reviewer", getattr(state, "profile_id", None))
        )
        result = await agent.invoke(state)
        score = result.get("review_score", 0.0)
        feedback = result.get("review_feedback", "")
        iteration = result.get("iteration_count", state.iteration_count + 1)
        emit("agent_result", agent="Reviewer", status="completed",
             score=score, passed=score >= 0.7)
        return {
            "review_score": score,
            "review_feedback": feedback,
            "iteration_count": iteration,
        }
    except Exception as e:
        logger.warning(f"Reviewer node LLM call failed, using fallback: {e}")
        emit("node_error", node="reviewer", error=str(e))

    # Fallback: heuristic scoring
    if state.report_draft:
        word_count = len(state.report_draft.split())
        score = min(0.9, 0.3 + word_count * 0.0005)
        feedback = f"Report contains {word_count} words. Structure is complete."
    else:
        score = 0.0
        feedback = "No report draft available to review."

    emit("agent_result", agent="Reviewer", status="fallback",
         score=score)
    return {
        "review_score": score,
        "review_feedback": feedback,
        "iteration_count": state.iteration_count + 1,
    }


async def formatter_node(state: ResearchState) -> Dict[str, Any]:
    """Formatter node that produces the final report and persists to KnowledgeMemory."""
    emit("agent_status", agent="Formatter", status="running",
         detail="Producing final report output")
    try:
        final = state.report_draft

        # Collect RAG sources from research_data and append a references section
        rag_sources = set()
        for item in state.research_data:
            if item.get("tool") == "rag":
                raw = str(item.get("raw_result", "") or "")
                # Try to extract source names from results
                import json as _json
                try:
                    parsed = _json.loads(raw)
                    if isinstance(parsed, dict) and "results" in parsed:
                        for r in parsed["results"]:
                            src = r.get("metadata", {}).get("source", "") or r.get("source", "")
                            if src:
                                rag_sources.add(src)
                except Exception:
                    # fallback: try to match [来源: xxx] citation patterns
                    import re as _re
                    for m in _re.finditer(r'来源:\s*([^\]]+)', raw):
                        rag_sources.add(m.group(1).strip())

        if rag_sources:
            final += "\n\n---\n"
            final += "## 知识库引用来源\n\n"
            final += "本次研究参考了知识库中的以下文档：\n\n"
            for i, src in enumerate(sorted(rag_sources), 1):
                final += f"{i}. {src}\n"

        final += "\n\n---\n*Report generated by DeepResearch-Agent*"

        updates: Dict[str, Any] = {
            "final_report": final,
            "status": "completed",
        }

        # Persist to KnowledgeMemory for cross-session reuse
        try:
            km = _get_knowledge_memory()
            report_id = await km.save_report(
                task=state.task,
                report=final,
                tags=["auto-saved"],
            )
            updates["knowledge_report_id"] = report_id
            logger.info("Saved final report to KnowledgeMemory (id=%s)", report_id)
        except Exception as exc:
            logger.warning("Failed to persist report to KnowledgeMemory: %s", exc)

        emit("agent_result", agent="Formatter", status="completed",
             report_length=len(final))
        return updates
    except Exception as exc:
        logger.exception("Formatter node failed")
        emit("node_error", node="formatter", error=str(exc))
        return {"status": "failed", "errors": state.errors + [str(exc)]}
