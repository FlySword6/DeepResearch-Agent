"""Tests for the ResearchService."""

import asyncio

import pytest

from app.services.research_service import ResearchService


@pytest.fixture
def service():
    """Create a fresh ResearchService for each test."""
    return ResearchService()


@pytest.fixture
async def cleanup():
    """Yield then a brief wait so fire-and-forget tasks can drain."""
    yield
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_start_research_returns_task_id(service):
    """Starting research should return a valid task_id."""
    task_id = await service.start_research("What is Python?")
    assert task_id is not None
    assert task_id.startswith("task_")


@pytest.mark.asyncio
async def test_start_research_with_custom_task_id(service):
    """Starting research with a custom task_id should use it."""
    custom_id = "my-test-task-42"
    task_id = await service.start_research("Test task", task_id=custom_id)
    assert task_id == custom_id


@pytest.mark.asyncio
async def test_get_status_returns_dict(service):
    """get_status should return a dict with expected keys."""
    task_id = await service.start_research("What is Python?")
    status = await service.get_status(task_id)
    assert status is not None
    assert "task_id" in status
    assert "status" in status
    assert "completed" in status
    assert status["task_id"] == task_id


@pytest.mark.asyncio
async def test_get_status_returns_none_for_unknown(service):
    """get_status for unknown task_id should return None."""
    status = await service.get_status("nonexistent")
    assert status is None


@pytest.mark.asyncio
async def test_get_events_queue_returns_queue(service):
    """get_events_queue should return an asyncio.Queue."""
    task_id = await service.start_research("Test task")
    queue = service.get_events_queue(task_id)
    assert queue is not None
    assert isinstance(queue, asyncio.Queue)


@pytest.mark.asyncio
async def test_get_events_queue_returns_none_for_unknown(service):
    """get_events_queue for unknown task_id should return None."""
    queue = service.get_events_queue("nonexistent")
    assert queue is None


@pytest.mark.asyncio
async def test_cancel_task_returns_true_for_running(service):
    """cancel_task should return True for a running task."""
    task_id = await service.start_research("Test task")
    await asyncio.sleep(0.05)
    result = await service.cancel_task(task_id)
    assert result is True
    # Wait for cancel event to drain
    await asyncio.sleep(0.05)


@pytest.mark.asyncio
async def test_cancel_task_returns_false_for_unknown(service):
    """cancel_task for unknown should return False."""
    result = await service.cancel_task("nonexistent")
    assert result is False


@pytest.mark.asyncio
async def test_get_state_returns_state(service):
    """get_state should return a ResearchState for tracked tasks."""
    task_id = await service.start_research("Test task")
    state = service.get_state(task_id)
    assert state is not None
    assert state.task == "Test task"
    assert state.status == "pending"


@pytest.mark.asyncio
async def test_get_state_returns_none_for_unknown(service):
    """get_state for unknown task_id should return None."""
    state = service.get_state("nonexistent")
    assert state is None


@pytest.mark.asyncio
async def test_list_tasks_returns_list(service):
    """list_tasks should return tracked tasks."""
    await service.start_research("Task 1", task_id="task-one")
    await service.start_research("Task 2", task_id="task-two")
    tasks = service.list_tasks()
    assert len(tasks) >= 2
    task_ids = {t["task_id"] for t in tasks}
    assert "task-one" in task_ids
    assert "task-two" in task_ids


@pytest.mark.asyncio
async def test_event_publishing(service):
    """Events should be published to the task's queue."""
    task_id = await service.start_research("Test task")
    queue = service.get_events_queue(task_id)

    # Manually push an event
    await service._push_event(task_id, "test_event", {"msg": "hello"})

    # Read from queue
    event = await asyncio.wait_for(queue.get(), timeout=2.0)
    assert event["type"] == "test_event"
    assert event["msg"] == "hello"
