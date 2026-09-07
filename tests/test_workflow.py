"""Tests for the LangGraph workflow graph."""

import pytest

from app.models.state import ResearchState, SubTask
from app.workflow.events import set_event_callback
from app.workflow.graph import build_graph
from app.workflow.nodes import (
    executor_node,
    router_decision,
)


class TestResearchState:
    """Test ResearchState model creation."""

    def test_create_state(self):
        state = ResearchState(task="Test task")
        assert state.task == "Test task"
        assert state.status == "pending"
        assert state.plan == []
        assert state.current_step == 0
        assert state.report_draft == ""

    def test_subtask_model(self):
        st = SubTask(id="step-1", description="Do something", tool="search")
        assert st.id == "step-1"
        assert st.status == "pending"
        assert st.result is None


class TestRouterDecision:
    """Test router_decision logic (replaces old router_node)."""

    def test_router_no_plan(self):
        state = ResearchState(task="test")
        assert router_decision(state) == "planner"

    def test_router_has_plan(self):
        state = ResearchState(
            task="test",
            plan=[SubTask(id="s1", description="Step 1", tool="search")],
        )
        assert router_decision(state) == "researcher"

    def test_router_complete(self):
        state = ResearchState(
            task="test",
            plan=[SubTask(id="s1", description="Step 1", tool="search")],
            current_step=1,
        )
        assert router_decision(state) == "writer"

    def test_router_failed(self):
        state = ResearchState(task="test", status="failed")
        assert router_decision(state) == "END"

    def test_router_low_score_loops_back(self):
        state = ResearchState(
            task="test",
            plan=[SubTask(id="s1", description="Step 1", tool="search")],
            current_step=1,
            report_draft="draft",
            review_score=0.5,
            iteration_count=0,
        )
        assert router_decision(state) == "writer"

    def test_router_good_score_goes_to_formatter(self):
        state = ResearchState(
            task="test",
            plan=[SubTask(id="s1", description="Step 1", tool="search")],
            current_step=1,
            report_draft="draft",
            review_score=0.85,
        )
        assert router_decision(state) == "formatter"


class TestGraphBuilding:
    """Test that the graph compiles and runs."""

    def test_graph_compiles(self):
        graph = build_graph()
        assert graph is not None

    @pytest.mark.asyncio
    async def test_graph_runs_simple_flow(self):
        """Test the graph runs end-to-end with a simple flow.

        NOTE: This test requires a live LLM API key. It will be skipped
        if neither OPENAI_API_KEY nor ANTHROPIC_API_KEY is set.
        """
        import os
        has_key = bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY"))
        if not has_key:
            pytest.skip("No LLM API key configured — skipping end-to-end graph test")

        set_event_callback(None)

        graph = build_graph()
        state = ResearchState(task="What is Python?")
        result = await graph.ainvoke(state)

        assert result is not None
        assert isinstance(result, dict) or isinstance(result, ResearchState)

        if isinstance(result, dict):
            final_report = result.get("final_report", "")
        else:
            final_report = result.final_report
        # The graph should produce a final report (even if fallback)
        assert final_report != ""


class TestExecutorNode:
    """Test the executor node."""

    @pytest.mark.asyncio
    async def test_executor_executes_step(self):
        state = ResearchState(
            task="test",
            plan=[SubTask(id="s1", description="Step 1", tool="search")],
        )
        result = await executor_node(state)
        assert result["current_step"] == 1
        assert len(result["research_data"]) == 1

    @pytest.mark.asyncio
    async def test_executor_no_steps_left(self):
        state = ResearchState(
            task="test",
            plan=[SubTask(id="s1", description="Step 1", tool="search")],
            current_step=1,
        )
        result = await executor_node(state)
        assert result.get("current_step", 1) == 1
