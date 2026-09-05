"""Pytest fixtures for DeepResearch-Agent tests."""

import pytest


@pytest.fixture
def research_task() -> str:
    """Return a sample research task."""
    return "What are the latest advances in quantum computing?"


@pytest.fixture
def sample_subtask_data() -> list:
    """Return sample subtask data."""
    return [
        {"id": "background", "description": "Research background", "tool": "search"},
        {"id": "analysis", "description": "Analyze findings", "tool": "analyze"},
    ]
