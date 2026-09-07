"""Comprehensive tests for the Multi-Agent architecture."""

import json

import pytest

from app.agents.planner import PlannerAgent
from app.agents.researcher import ResearcherAgent
from app.agents.reviewer import ReviewerAgent
from app.agents.writer import WriterAgent
from app.models.state import ResearchState, SubTask
from app.tools.base import ToolResult
from app.tools.router import ToolRouter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_llm_array(monkeypatch):
    """Mock llm_call to return a JSON array of subtasks."""
    async def fake_llm_call(system_prompt: str, user_prompt: str, **kwargs):
        return json.dumps([
            {"id": "step-1", "description": "Research background", "tool": "search"},
            {"id": "step-2", "description": "Analyze findings", "tool": "analyze"},
            {"id": "step-3", "description": "Deep dive into details", "tool": "browse"},
        ])
    monkeypatch.setattr("app.agents.planner.llm_call", fake_llm_call)
    return fake_llm_call


@pytest.fixture
def mock_llm_subtasks_dict(monkeypatch):
    """Mock llm_call to return a dict with 'subtasks' key."""
    async def fake_llm_call(system_prompt: str, user_prompt: str, **kwargs):
        return json.dumps({
            "subtasks": [
                {"id": "s1", "description": "Step one", "tool": "search"},
                {"id": "s2", "description": "Step two", "tool": "analyze"},
            ]
        })
    monkeypatch.setattr("app.agents.planner.llm_call", fake_llm_call)
    return fake_llm_call


@pytest.fixture
def mock_llm_fail(monkeypatch):
    """Mock llm_call to raise an exception, forcing fallback."""
    async def fake_llm_call(system_prompt: str, user_prompt: str, **kwargs):
        raise ValueError("API key not configured")
    monkeypatch.setattr("app.agents.planner.llm_call", fake_llm_call)
    return fake_llm_call


@pytest.fixture
def mock_llm_writer(monkeypatch):
    """Mock llm_call for WriterAgent."""
    async def fake_llm_call(system_prompt: str, user_prompt: str, **kwargs):
        return "# Test Report\n\n## Abstract\nThis is a test report."
    monkeypatch.setattr("app.agents.writer.llm_call", fake_llm_call)
    return fake_llm_call


@pytest.fixture
def mock_llm_reviewer(monkeypatch):
    """Mock llm_call for ReviewerAgent to return a review JSON."""
    async def fake_llm_call(system_prompt: str, user_prompt: str, **kwargs):
        return json.dumps({
            "score": 0.85,
            "feedback": "Good report with clear structure.",
            "passed": True,
        })
    monkeypatch.setattr("app.agents.reviewer.llm_call", fake_llm_call)
    return fake_llm_call


@pytest.fixture
def mock_llm_researcher(monkeypatch):
    """Mock llm_call for ResearcherAgent summarization."""
    async def fake_llm_call(system_prompt: str, user_prompt: str, **kwargs):
        return "- Key finding one\n- Key finding two\n- Key finding three"
    monkeypatch.setattr("app.agents.researcher.llm_call", fake_llm_call)
    return fake_llm_call


@pytest.fixture
def basic_state() -> ResearchState:
    return ResearchState(task="Test research task")


@pytest.fixture
def state_with_plan() -> ResearchState:
    return ResearchState(
        task="What is the impact of AI on healthcare?",
        plan=[
            SubTask(id="background", description="Research AI in healthcare background", tool="search"),
            SubTask(id="analysis", description="Analyze key trends", tool="analyze"),
        ],
    )


@pytest.fixture
def mock_tool_router(monkeypatch) -> ToolRouter:
    """Create a ToolRouter with mocked tool executions."""
    router = ToolRouter()

    async def fake_search(query: str, max_results: int = 5, **kwargs):
        return ToolResult(
            success=True,
            data=[
                {"title": "AI in Healthcare", "url": "https://example.com", "snippet": "AI transforms healthcare."},
            ],
            metadata={"source": "mock", "result_count": 1},
        )

    async def fake_browse(url: str, **kwargs):
        return ToolResult(
            success=True,
            data={"title": "Healthcare AI", "content": "Detailed content about AI in healthcare.", "url": url},
        )

    async def fake_analyze(code: str, timeout: int = 30, **kwargs):
        return ToolResult(
            success=True,
            data={"stdout": "Analysis complete.\n", "stderr": ""},
        )

    router._tools["search"].execute = fake_search
    router._tools["browse"].execute = fake_browse
    router._tools["analyze"].execute = fake_analyze

    return router


# ---------------------------------------------------------------------------
# PlannerAgent Tests
# ---------------------------------------------------------------------------

class TestPlannerAgent:
    """Tests for PlannerAgent."""

    @pytest.mark.asyncio
    async def test_planner_returns_plan_with_mock(self, mock_llm_array, basic_state):
        """Planner should return a plan when LLM returns valid JSON array."""
        agent = PlannerAgent()
        result = await agent.invoke(basic_state)
        assert "plan" in result
        assert len(result["plan"]) >= 3
        assert result["plan"][0].id == "step-1"
        assert result["plan"][0].tool == "search"

    @pytest.mark.asyncio
    async def test_planner_handles_subtasks_dict(self, mock_llm_subtasks_dict, basic_state):
        """Planner should parse dict with 'subtasks' key."""
        agent = PlannerAgent()
        result = await agent.invoke(basic_state)
        assert "plan" in result
        assert len(result["plan"]) == 2
        assert result["plan"][0].id == "s1"

    @pytest.mark.asyncio
    async def test_planner_fallback_on_failure(self, mock_llm_fail, basic_state):
        """Planner should fall back to hardcoded plan when LLM fails."""
        agent = PlannerAgent()
        result = await agent.invoke(basic_state)
        assert "plan" in result
        assert len(result["plan"]) >= 3
        assert result["plan"][0].tool in ("search", "browse", "analyze")

    @pytest.mark.asyncio
    async def test_planner_subtask_structure(self, mock_llm_array, basic_state):
        """Each subtask should have correct fields."""
        agent = PlannerAgent()
        result = await agent.invoke(basic_state)
        for st in result["plan"]:
            assert st.id
            assert st.description
            assert st.tool in ("search", "browse", "analyze")
            assert st.status == "pending"

    def test_system_prompt(self):
        """System prompt should mention planning."""
        agent = PlannerAgent()
        prompt = agent.system_prompt()
        assert "规划" in prompt or "subtask" in prompt.lower()

    def test_parse_subtasks_markdown_fenced(self):
        """_parse_subtasks should handle markdown fenced JSON."""
        agent = PlannerAgent()
        response = """Here is the plan:
```json
[{"id": "test", "description": "Test task", "tool": "search"}]
```"""
        result = agent._parse_subtasks(response)
        assert result is not None
        assert len(result) == 1
        assert result[0]["id"] == "test"

    def test_parse_subtasks_raw_json(self):
        """_parse_subtasks should handle raw JSON."""
        agent = PlannerAgent()
        response = '[{"id": "test", "description": "Test task", "tool": "browse"}]'
        result = agent._parse_subtasks(response)
        assert result is not None
        assert len(result) == 1
        assert result[0]["tool"] == "browse"

    def test_parse_subtasks_dict_with_subtasks(self):
        """_parse_subtasks should handle dict with 'subtasks' key."""
        agent = PlannerAgent()
        response = '{"subtasks": [{"id": "s1", "description": "Step 1", "tool": "search"}]}'
        result = agent._parse_subtasks(response)
        assert result is not None
        assert len(result) == 1
        assert result[0]["id"] == "s1"

    def test_parse_subtasks_invalid_json(self):
        """_parse_subtasks should return None for invalid JSON."""
        agent = PlannerAgent()
        result = agent._parse_subtasks("Not JSON at all")
        assert result is None


# ---------------------------------------------------------------------------
# ResearcherAgent Tests
# ---------------------------------------------------------------------------

class TestResearcherAgent:
    """Tests for ResearcherAgent."""

    @pytest.mark.asyncio
    async def test_researcher_executes_search(self, mock_llm_researcher, state_with_plan, mock_tool_router):
        """Researcher should execute search tool and return result."""
        agent = ResearcherAgent()
        result = await agent.invoke(state_with_plan, tools=mock_tool_router)
        assert "research_data" in result
        assert len(result["research_data"]) == 1
        assert result["research_data"][0]["step"] == 0
        assert result["research_data"][0]["tool"] == "search"
        assert "current_step" in result
        assert result["current_step"] == 1

    @pytest.mark.asyncio
    async def test_researcher_advances_step(self, mock_llm_researcher, state_with_plan, mock_tool_router):
        """Researcher should advance current_step by 1."""
        agent = ResearcherAgent()
        result = await agent.invoke(state_with_plan, tools=mock_tool_router)
        assert result["current_step"] == state_with_plan.current_step + 1

    @pytest.mark.asyncio
    async def test_researcher_no_tools_fallback(self, state_with_plan):
        """Researcher should work without ToolRouter (fallback message)."""
        agent = ResearcherAgent()
        result = await agent.invoke(state_with_plan, tools=None)
        assert "research_data" in result
        assert result["current_step"] == 1

    @pytest.mark.asyncio
    async def test_researcher_extract_url(self):
        """_extract_url should find URLs in descriptions."""
        agent = ResearcherAgent()
        url = agent._extract_url("Read https://example.com/page for details")
        assert url == "https://example.com/page"

    @pytest.mark.asyncio
    async def test_researcher_extract_url_none(self):
        """_extract_url should return None when no URL present."""
        agent = ResearcherAgent()
        url = agent._extract_url("Research background of AI")
        assert url is None

    @pytest.mark.asyncio
    async def test_researcher_fallback_summary(self):
        """_fallback_summary should return the input text for plain strings."""
        summary = ResearcherAgent._fallback_summary("Some data here")
        assert "Some data here" in summary

    def test_system_prompt(self):
        """System prompt should mention research analysis."""
        agent = ResearcherAgent()
        prompt = agent.system_prompt()
        assert "研究" in prompt or "research" in prompt.lower()


# ---------------------------------------------------------------------------
# WriterAgent Tests
# ---------------------------------------------------------------------------

class TestWriterAgent:
    """Tests for WriterAgent."""

    @pytest.mark.asyncio
    async def test_writer_uses_llm(self, mock_llm_writer, state_with_plan):
        """Writer should call LLM and return report draft."""
        agent = WriterAgent()
        result = await agent.invoke(state_with_plan)
        assert "report_draft" in result
        assert result["report_draft"] != ""

    @pytest.mark.asyncio
    async def test_writer_fallback(self, state_with_plan):
        """Writer should produce fallback report when LLM fails."""
        state_with_plan.research_data = [
            {"step": 0, "description": "Test step", "summary": "Test result", "tool": "search"},
        ]
        agent = WriterAgent()
        result = await agent.invoke(state_with_plan)
        assert "report_draft" in result
        # Fallback path due to llm_call raising exception (no mock, no API key)
        draft = result["report_draft"]
        assert len(draft) > 50

    @pytest.mark.asyncio
    async def test_writer_uses_research_data(self, mock_llm_writer, state_with_plan):
        """Writer should incorporate research data into report."""
        state_with_plan.research_data = [
            {"step": 0, "description": "Impact of AI on diagnosis", "summary": "AI improves diagnosis accuracy by 30%", "tool": "search"},
            {"step": 1, "description": "Analysis of trends", "summary": "Growing adoption in radiology", "tool": "analyze"},
        ]
        agent = WriterAgent()
        result = await agent.invoke(state_with_plan)
        report = result["report_draft"]
        assert len(report) > 0
        assert "# Test Report" in report  # from mock

    def test_format_plan(self, state_with_plan):
        """_format_plan should produce readable plan string."""
        agent = WriterAgent()
        formatted = agent._format_plan(state_with_plan)
        assert "search" in formatted
        assert "analyze" in formatted
        assert "background" in formatted

    def test_system_prompt(self):
        """System prompt should mention report writing."""
        agent = WriterAgent()
        prompt = agent.system_prompt()
        assert len(prompt) > 50


# ---------------------------------------------------------------------------
# ReviewerAgent Tests
# ---------------------------------------------------------------------------

class TestReviewerAgent:
    """Tests for ReviewerAgent."""

    @pytest.mark.asyncio
    async def test_reviewer_scores_report(self, mock_llm_reviewer, state_with_plan):
        """Reviewer should return score and feedback when LLM works."""
        state_with_plan.report_draft = "# Test Report\n\n## Abstract\nDetails here."
        agent = ReviewerAgent()
        result = await agent.invoke(state_with_plan)
        assert "review_score" in result
        assert "review_feedback" in result
        assert result["review_score"] == 0.85
        assert result["iteration_count"] == state_with_plan.iteration_count + 1

    @pytest.mark.asyncio
    async def test_reviewer_handles_no_report(self, state_with_plan):
        """Reviewer should return 0 score when no report exists."""
        agent = ReviewerAgent()
        result = await agent.invoke(state_with_plan)
        assert result["review_score"] == 0.0
        assert "No report draft" in result["review_feedback"]

    @pytest.mark.asyncio
    async def test_reviewer_heuristic_fallback(self, state_with_plan):
        """Reviewer should use heuristic scoring when LLM fails."""
        state_with_plan.report_draft = (
            "# Test Report\n\n"
            "## Abstract\nThis is a test report with substantial content. "
            "It contains multiple sentences and should be long enough to trigger "
            "the length heuristic. We need at least 200 words here so the test "
            "can properly verify the heuristic scoring logic. "
            "Adding more content to reach the threshold. "
            "And even more content. And some numbers like 42 and 100. "
            "References: https://example.com and other sources. "
            "This report discusses background information and findings. "
            "It also covers analysis and conclusions. "
            "One two three four five six seven eight nine ten. "
        )
        # Repeat content to reach word count
        state_with_plan.report_draft += "\n\n" + state_with_plan.report_draft * 3
        state_with_plan.plan = []
        agent = ReviewerAgent()
        result = await agent.invoke(state_with_plan)
        assert "review_score" in result
        assert result["review_score"] > 0
        assert result["iteration_count"] == 1

    def test_parse_review_valid_json(self):
        """_parse_review should parse valid JSON review."""
        agent = ReviewerAgent()
        response = '{"score": 0.9, "feedback": "Great work!", "passed": true}'
        result = agent._parse_review(response)
        assert result["score"] == 0.9
        assert result["feedback"] == "Great work!"
        assert result["passed"] is True

    def test_parse_review_markdown_fenced(self):
        """_parse_review should handle markdown-wrapped JSON."""
        agent = ReviewerAgent()
        response = "Review:\n```json\n{\"score\": 0.75, \"feedback\": \"Good\", \"passed\": true}\n```"
        result = agent._parse_review(response)
        assert result["score"] == 0.75
        assert result["feedback"] == "Good"

    def test_parse_review_invalid(self):
        """_parse_review should return defaults for invalid JSON."""
        agent = ReviewerAgent()
        result = agent._parse_review("Not valid JSON")
        assert result["score"] == 0.0
        assert result["passed"] is False

    def test_system_prompt(self):
        """System prompt should mention quality assurance."""
        agent = ReviewerAgent()
        prompt = agent.system_prompt()
        assert "reviewer" in prompt.lower() or "quality" in prompt.lower()


# ---------------------------------------------------------------------------
# Integration / Workflow Tests
# ---------------------------------------------------------------------------

class TestWorkflowIntegration:
    """Tests for end-to-end workflow through agents."""

    @pytest.mark.asyncio
    async def test_planner_to_researcher_flow(self, mock_llm_array, mock_llm_researcher, mock_tool_router):
        """Planner -> Researcher flow should produce research data."""
        # Step 1: Plan
        planner = PlannerAgent()
        state = ResearchState(task="What is the impact of AI on healthcare?")
        plan_result = await planner.invoke(state)
        assert len(plan_result["plan"]) == 3

        # Apply plan to state
        state.plan = plan_result["plan"]

        # Step 2: Execute first subtask
        researcher = ResearcherAgent()
        research_result = await researcher.invoke(state, tools=mock_tool_router)
        assert len(research_result["research_data"]) == 1
        assert research_result["current_step"] == 1

        # Step 3: Execute second subtask
        state.research_data = research_result["research_data"]
        state.current_step = research_result["current_step"]
        research_result2 = await researcher.invoke(state, tools=mock_tool_router)
        assert research_result2["current_step"] == 2

    @pytest.mark.asyncio
    async def test_writer_and_reviewer_flow(self, mock_llm_writer, mock_llm_reviewer, state_with_plan):
        """Writer -> Reviewer flow should produce and score report."""
        state_with_plan.research_data = [
            {"step": 0, "description": "Background", "summary": "AI in healthcare is growing.", "tool": "search"},
        ]

        # Writer
        writer = WriterAgent()
        write_result = await writer.invoke(state_with_plan)
        assert write_result["report_draft"]

        # Reviewer
        state_with_plan.report_draft = write_result["report_draft"]
        reviewer = ReviewerAgent()
        review_result = await reviewer.invoke(state_with_plan)
        assert review_result["review_score"] > 0
        assert review_result["iteration_count"] == 1

    @pytest.mark.asyncio
    async def test_full_pipeline_fallback_path(self):
        """Full pipeline should work even without LLM mocks (using fallbacks)."""
        state = ResearchState(task="Test fallback pipeline")

        # Planner (will use fallback since no API key)
        planner = PlannerAgent()
        plan_result = await planner.invoke(state)
        assert plan_result["plan"]
        state.plan = plan_result["plan"]

        # Researcher with no tools (will use fallback message)
        researcher = ResearcherAgent()
        res_result = await researcher.invoke(state, tools=None)
        assert res_result["research_data"]
        state.research_data = res_result["research_data"]
        state.current_step = res_result["current_step"]

        # Writer (will use fallback)
        writer = WriterAgent()
        write_result = await writer.invoke(state)
        assert write_result["report_draft"]
        state.report_draft = write_result["report_draft"]

        # Reviewer (will use heuristic)
        reviewer = ReviewerAgent()
        review_result = await reviewer.invoke(state)
        assert "review_score" in review_result
        assert "review_feedback" in review_result

    @pytest.mark.asyncio
    async def test_agent_imports(self):
        """All agent classes should be importable."""
        from app.agents import BaseAgent, PlannerAgent, ResearcherAgent, ReviewerAgent, WriterAgent
        assert BaseAgent
        assert PlannerAgent
        assert ResearcherAgent
        assert WriterAgent
        assert ReviewerAgent
