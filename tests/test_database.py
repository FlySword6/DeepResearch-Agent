"""Tests for the SQLite database persistence layer.

Covers TaskRepository, ReportRepository, TaskEventRepository CRUD operations
and the init_db / close_db lifecycle.
"""

import pytest

from app.models.database import (
    TaskModel,
    ReportModel,
    TaskEventModel,
    TaskRepository,
    ReportRepository,
    TaskEventRepository,
    init_db,
    close_db,
)


@pytest.fixture
async def db():
    """Initialise an in-memory SQLite database for testing."""
    await init_db("sqlite+aiosqlite://")
    yield
    await close_db()


@pytest.fixture
async def session(db):
    """Provide an async session within a test."""
    from app.models.database import _async_session_maker

    async with _async_session_maker() as s:
        yield s


# ======================================================================
# TaskRepository
# ======================================================================


class TestTaskRepository:
    async def test_create_and_get(self, session):
        repo = TaskRepository(session)
        task = TaskModel(id="t1", task_text="research topic", status="pending")
        created = await repo.create(task)
        assert created.id == "t1"

        fetched = await repo.get("t1")
        assert fetched is not None
        assert fetched.task_text == "research topic"

    async def test_get_missing(self, session):
        repo = TaskRepository(session)
        assert await repo.get("nonexistent") is None

    async def test_update(self, session):
        repo = TaskRepository(session)
        task = TaskModel(id="t2", task_text="update test")
        await repo.create(task)

        task.status = "completed"
        task.report = "final report content"
        await repo.update(task)

        updated = await repo.get("t2")
        assert updated.status == "completed"
        assert updated.report == "final report content"

    async def test_list_recent(self, session):
        repo = TaskRepository(session)
        for i in range(3):
            await repo.create(TaskModel(id=f"t{i}", task_text=f"task {i}"))
        tasks = await repo.list_recent()
        assert len(tasks) == 3

    async def test_list_empty(self, session):
        repo = TaskRepository(session)
        assert await repo.list_recent() == []

    async def test_delete(self, session):
        repo = TaskRepository(session)
        await repo.create(TaskModel(id="to-del", task_text="delete me"))
        assert await repo.delete("to-del") is True
        assert await repo.get("to-del") is None

    async def test_delete_missing(self, session):
        repo = TaskRepository(session)
        assert await repo.delete("nonexistent") is False


# ======================================================================
# ReportRepository
# ======================================================================


class TestReportRepository:
    async def test_create_and_get(self, session):
        repo = ReportRepository(session)
        report = ReportModel(id="r1", task_id="t1", content="# Report", format="markdown")
        created = await repo.create(report)
        assert created.id == "r1"

        fetched = await repo.get("r1")
        assert fetched is not None
        assert fetched.content == "# Report"

    async def test_get_by_task(self, session):
        repo = ReportRepository(session)
        for i in range(2):
            await repo.create(ReportModel(id=f"r{i}", task_id="t1", content=f"report {i}"))
        reports = await repo.get_by_task("t1")
        assert len(reports) == 2

    async def test_get_by_task_empty(self, session):
        repo = ReportRepository(session)
        assert await repo.get_by_task("nonexistent") == []

    async def test_delete_by_task(self, session):
        repo = ReportRepository(session)
        await repo.create(ReportModel(id="r1", task_id="t1", content="c"))
        await repo.create(ReportModel(id="r2", task_id="t1", content="c"))
        count = await repo.delete_by_task("t1")
        assert count == 2
        assert await repo.get_by_task("t1") == []


# ======================================================================
# TaskEventRepository
# ======================================================================


class TestTaskEventRepository:
    async def test_add_and_get_events(self, session):
        repo = TaskEventRepository(session)
        await repo.add_event("t1", "agent_status", {"agent": "planner", "status": "running"})
        await repo.add_event("t1", "agent_result", {"agent": "planner", "status": "completed"})

        events = await repo.get_events("t1")
        assert len(events) == 2
        assert events[0].event_type == "agent_status"
        assert events[1].event_type == "agent_result"

    async def test_get_events_empty(self, session):
        repo = TaskEventRepository(session)
        assert await repo.get_events("nonexistent") == []

    async def test_get_events_limit(self, session):
        repo = TaskEventRepository(session)
        for i in range(5):
            await repo.add_event("t1", "test", {"i": i})
        events = await repo.get_events("t1", limit=3)
        assert len(events) == 3
