"""Conditional edge functions for the LangGraph workflow."""

from typing import Dict

from app.models.state import ResearchState


def is_plan_complete(state: ResearchState) -> str:
    """
    Check if the research plan has been created.

    Returns node name or 'END'.
    """
    if state.plan and len(state.plan) > 0:
        return "researcher"
    return "planner"


def is_research_complete(state: ResearchState) -> str:
    """
    Check if all research steps are done.

    Returns node name or 'END'.
    """
    if state.current_step >= len(state.plan):
        return "writer"
    return "researcher"


def should_continue(state: ResearchState) -> str:
    """
    Main routing condition for the workflow.

    Maps state to the next node name or 'END'.
    """
    from app.workflow.nodes import router_decision

    return router_decision(state)
