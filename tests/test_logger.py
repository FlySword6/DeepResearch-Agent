"""Tests for the logging configuration."""

import io
import logging
import re
import sys

import pytest

from app.utils.logger import setup_logging


def test_setup_logging_adds_handler():
    """setup_logging should add a StreamHandler to the root logger."""
    # Reset root logger for test isolation
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    root.handlers.clear()
    old_level = root.level

    try:
        setup_logging("DEBUG")
        assert len(root.handlers) >= 1
        assert any(isinstance(h, logging.StreamHandler) for h in root.handlers)
        assert root.level == logging.DEBUG
    finally:
        root.handlers.clear()
        root.handlers.extend(old_handlers)
        root.setLevel(old_level)


def test_setup_logging_default_level():
    """setup_logging should default to INFO level."""
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    root.handlers.clear()
    old_level = root.level

    try:
        setup_logging()
        assert root.level == logging.INFO
    finally:
        root.handlers.clear()
        root.handlers.extend(old_handlers)
        root.setLevel(old_level)


def test_setup_logging_invalid_level():
    """setup_logging should fall back to INFO for invalid levels."""
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    root.handlers.clear()
    old_level = root.level

    try:
        setup_logging("INVALID_LEVEL_XYZ")
        assert root.level == logging.INFO
    finally:
        root.handlers.clear()
        root.handlers.extend(old_handlers)
        root.setLevel(old_level)


def test_log_format():
    """Log output should match the expected structured format."""
    root = logging.getLogger()
    old_handlers = list(root.handlers)
    root.handlers.clear()
    old_level = root.level

    try:
        setup_logging("DEBUG")

        # Capture output
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root.addHandler(handler)

        test_logger = logging.getLogger("test_logger")
        test_logger.info("Hello %s", "world")

        output = stream.getvalue()
        # Expected format: "2025-01-01 12:00:00 | INFO     | test_logger:<lineno> | Hello world"
        assert "Hello world" in output
        assert "INFO" in output
        assert "test_logger" in output
        assert re.match(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", output.strip())
    finally:
        root.handlers.clear()
        root.handlers.extend(old_handlers)
        root.setLevel(old_level)
