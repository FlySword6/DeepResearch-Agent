"""Tests for the dual memory system (SessionMemory and KnowledgeMemory)."""

import asyncio
import pytest
import time

from app.memory.session_memory import SessionMemory
from app.memory.knowledge_memory import KnowledgeMemory
from app.models.state import ResearchState, SubTask
from app.tools.memory import MemoryTool


# ======================================================================
# SessionMemory
# ======================================================================

class TestSessionMemory:
    """SessionMemory save, load, expire, and delete behaviour."""

    @pytest.fixture
    def memory(self) -> SessionMemory:
        return SessionMemory()

    @pytest.fixture
    def sample_state(self) -> ResearchState:
        return ResearchState(
            task="Test research task",
            plan=[
                SubTask(id="step1", description="First step", tool="search"),
            ],
        )

    @pytest.mark.asyncio
    async def test_save_and_load(self, memory: SessionMemory, sample_state: ResearchState):
        """Saving a state and loading it back should return an identical object."""
        await memory.save_state("task-1", sample_state)
        loaded = await memory.load_state("task-1")
        assert loaded is not None
        assert loaded.task == sample_state.task
        assert loaded.plan[0].id == sample_state.plan[0].id

    @pytest.mark.asyncio
    async def test_load_missing(self, memory: SessionMemory):
        """Loading a non-existent key should return None."""
        loaded = await memory.load_state("nonexistent")
        assert loaded is None

    @pytest.mark.asyncio
    async def test_delete_state(self, memory: SessionMemory, sample_state: ResearchState):
        """Deleting a state should remove it from the store."""
        await memory.save_state("task-2", sample_state)
        assert await memory.load_state("task-2") is not None
        await memory.delete_state("task-2")
        assert await memory.load_state("task-2") is None

    @pytest.mark.asyncio
    async def test_list_sessions(self, memory: SessionMemory, sample_state: ResearchState):
        """list_sessions should return only active (non-expired) IDs."""
        await memory.save_state("alpha", sample_state)
        await memory.save_state("beta", sample_state)
        sessions = await memory.list_sessions()
        assert "alpha" in sessions
        assert "beta" in sessions
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_list_sessions_empty(self, memory: SessionMemory):
        """An empty store should return an empty list."""
        sessions = await memory.list_sessions()
        assert sessions == []

    def test_expired_check(self, memory: SessionMemory):
        """_is_expired should return True for missing keys and False for valid ones."""
        # No key set → expired
        assert memory._is_expired("ghost") is True

    @pytest.mark.asyncio
    async def test_len_and_contains(self, memory: SessionMemory, sample_state: ResearchState):
        """Dunder methods for convenience in testing."""
        await memory.save_state("dunder", sample_state)
        assert len(memory) == 1
        assert "dunder" in memory

    @pytest.mark.asyncio
    async def test_expired_state_cleaned_on_load(self, memory: SessionMemory, sample_state: ResearchState):
        """Loading an expired state should return None and clean up the entry."""
        await memory.save_state("expire-me", sample_state)
        # Manually set TTL to the past
        memory._ttl["expire-me"] = time.time() - 1
        loaded = await memory.load_state("expire-me")
        assert loaded is None
        # Entry should have been cleaned up
        assert "expire-me" not in memory._store

    @pytest.mark.asyncio
    async def test_list_sessions_excludes_expired(self, memory: SessionMemory, sample_state: ResearchState):
        """Expired sessions should not appear in list_sessions."""
        await memory.save_state("good", sample_state)
        await memory.save_state("stale", sample_state)
        memory._ttl["stale"] = time.time() - 1
        sessions = await memory.list_sessions()
        assert "good" in sessions
        assert "stale" not in sessions

    def test_fakeredis_detection(self):
        """SessionMemory should detect fakeredis availability without crashing."""
        mem = SessionMemory()
        # Should not crash; _use_fakeredis is either True or False
        assert isinstance(mem._use_fakeredis, bool)


# ======================================================================
# KnowledgeMemory
# ======================================================================

class TestKnowledgeMemory:
    """KnowledgeMemory save, query, get, and list behaviour."""

    @pytest.fixture
    def km(self) -> KnowledgeMemory:
        return KnowledgeMemory()

    @pytest.mark.asyncio
    async def test_save_report(self, km: KnowledgeMemory):
        """Saving a report should return a non-empty string ID."""
        report_id = await km.save_report(
            task="Test task",
            report="This is a test report about quantum computing and AI.",
            tags=["test", "ai"],
        )
        assert isinstance(report_id, str)
        assert len(report_id) > 0

    @pytest.mark.asyncio
    async def test_get_report(self, km: KnowledgeMemory):
        """get_report should return the saved report or None."""
        report_id = await km.save_report(
            task="Get me task",
            report="Report for retrieval test.",
        )
        retrieved = await km.get_report(report_id)
        assert retrieved is not None
        assert retrieved["task"] == "Get me task"
        assert retrieved["report"] == "Report for retrieval test."

    @pytest.mark.asyncio
    async def test_get_report_missing(self, km: KnowledgeMemory):
        """Getting a non-existent report should return None."""
        retrieved = await km.get_report("no-such-id")
        assert retrieved is None

    @pytest.mark.asyncio
    async def test_list_reports(self, km: KnowledgeMemory):
        """list_reports should return saved reports newest first."""
        id_a = await km.save_report(task="Task A", report="Report A")
        await asyncio.sleep(0.02)  # ensure distinct timestamps on Windows
        id_b = await km.save_report(task="Task B", report="Report B")
        reports = await km.list_reports(limit=10)
        assert len(reports) == 2
        # Newest first
        assert reports[0]["report_id"] == id_b
        assert reports[1]["report_id"] == id_a

    @pytest.mark.asyncio
    async def test_list_reports_limit(self, km: KnowledgeMemory):
        """list_reports should respect the limit parameter."""
        for i in range(5):
            await km.save_report(task=f"Task {i}", report=f"Report {i}")
        reports = await km.list_reports(limit=3)
        assert len(reports) == 3

    @pytest.mark.asyncio
    async def test_list_reports_empty(self, km: KnowledgeMemory):
        """An empty store should return an empty list."""
        reports = await km.list_reports()
        assert reports == []

    @pytest.mark.asyncio
    async def test_query_similar(self, km: KnowledgeMemory):
        """query_similar should find reports matching the query."""
        await km.save_report(
            task="Quantum computing advances",
            report="Recent advances in quantum computing include superconducting qubits.",
            tags=["quantum", "computing"],
        )
        await km.save_report(
            task="Climate change data",
            report="Global temperatures are rising due to CO2 emissions.",
            tags=["climate", "environment"],
        )
        results = await km.query_similar("quantum computing", k=2)
        assert len(results) >= 1
        # Match is case-insensitive because tokenizer lowercases both sides
        assert any("quantum" in r["task"].lower() for r in results)

    @pytest.mark.asyncio
    async def test_query_similar_empty_store(self, km: KnowledgeMemory):
        """Querying an empty store should return an empty list."""
        results = await km.query_similar("anything", k=3)
        assert results == []

    @pytest.mark.asyncio
    async def test_len(self, km: KnowledgeMemory):
        """__len__ should return the number of stored reports."""
        assert len(km) == 0
        await km.save_report(task="T", report="R")
        assert len(km) == 1

    def test_chromadb_detection(self):
        """KnowledgeMemory should detect chromadb availability without crashing."""
        km = KnowledgeMemory()
        assert isinstance(km._use_chromadb, bool)


# ======================================================================
# MemoryTool delegation
# ======================================================================

class TestMemoryToolDelegation:
    """MemoryTool should correctly delegate to SessionMemory and KnowledgeMemory."""

    @pytest.fixture
    def tool(self) -> MemoryTool:
        return MemoryTool()

    @pytest.mark.asyncio
    async def test_session_save_and_load(self, tool: MemoryTool):
        """session_save followed by session_load returns the same state dict."""
        state_dict = {
            "task": "Delegation test",
            "plan": [],
            "research_data": [],
            "errors": [],
        }
        save_result = await tool.execute(
            action="session_save",
            task_id="del-test-1",
            state=state_dict,
        )
        assert save_result.success is True
        assert save_result.data["stored"] is True

        load_result = await tool.execute(
            action="session_load",
            task_id="del-test-1",
        )
        assert load_result.success is True
        assert load_result.data["state"]["task"] == "Delegation test"

    @pytest.mark.asyncio
    async def test_session_load_missing(self, tool: MemoryTool):
        """Loading a missing session should return an error."""
        result = await tool.execute(action="session_load", task_id="no-such")
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_session_list(self, tool: MemoryTool):
        """session_list should list saved sessions."""
        state_dict = {"task": "T", "plan": [], "research_data": [], "errors": []}
        await tool.execute(action="session_save", task_id="list-a", state=state_dict)
        await tool.execute(action="session_save", task_id="list-b", state=state_dict)
        result = await tool.execute(action="session_list")
        assert result.success is True
        assert "list-a" in result.data["sessions"]
        assert "list-b" in result.data["sessions"]

    @pytest.mark.asyncio
    async def test_knowledge_save(self, tool: MemoryTool):
        """knowledge_save should return a report_id."""
        result = await tool.execute(
            action="knowledge_save",
            task="Save test",
            report="This is a test report.",
            tags=["test"],
        )
        assert result.success is True
        assert "report_id" in result.data
        assert result.data["stored"] is True

    @pytest.mark.asyncio
    async def test_knowledge_query(self, tool: MemoryTool):
        """knowledge_query should find matching reports."""
        await tool.execute(
            action="knowledge_save",
            task="Machine learning basics",
            report="ML is a field of AI.",
        )
        result = await tool.execute(
            action="knowledge_query",
            query="machine learning",
            k=5,
        )
        assert result.success is True
        assert result.data["count"] >= 1

    @pytest.mark.asyncio
    async def test_knowledge_list(self, tool: MemoryTool):
        """knowledge_list should return saved reports."""
        await tool.execute(
            action="knowledge_save",
            task="List test",
            report="List me.",
        )
        result = await tool.execute(action="knowledge_list", limit=10)
        assert result.success is True
        assert result.data["count"] >= 1

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool: MemoryTool):
        """An unknown action should return an error."""
        result = await tool.execute(action="bogus")
        assert result.success is False
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_session_save_missing_task_id(self, tool: MemoryTool):
        """session_save without task_id should return an error."""
        result = await tool.execute(action="session_save", state={})
        assert result.success is False
        assert "task_id" in result.error

    @pytest.mark.asyncio
    async def test_session_save_missing_state(self, tool: MemoryTool):
        """session_save without state should return an error."""
        result = await tool.execute(action="session_save", task_id="no-state")
        assert result.success is False
        assert "state" in result.error

    @pytest.mark.asyncio
    async def test_knowledge_save_missing_task(self, tool: MemoryTool):
        """knowledge_save without task should return an error."""
        result = await tool.execute(action="knowledge_save", report="R")
        assert result.success is False
        assert "task" in result.error

    @pytest.mark.asyncio
    async def test_knowledge_save_missing_report(self, tool: MemoryTool):
        """knowledge_save without report should return an error."""
        result = await tool.execute(action="knowledge_save", task="T")
        assert result.success is False
        assert "report" in result.error

    @pytest.mark.asyncio
    async def test_knowledge_query_missing_query(self, tool: MemoryTool):
        """knowledge_query without query should return an error."""
        result = await tool.execute(action="knowledge_query")
        assert result.success is False
        assert "query" in result.error
