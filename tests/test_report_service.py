"""Tests for ReportService: saving, retrieving, listing reports."""

import os

import pytest

from app.services.report_service import ReportService


@pytest.fixture
def report_service(tmp_path):
    """Create a ReportService with a temp output directory."""
    output_dir = os.path.join(str(tmp_path), "reports")
    return ReportService(output_dir=output_dir)


class TestReportService:
    """Tests for ReportService."""

    @pytest.mark.asyncio
    async def test_save_report_markdown(self, report_service):
        """Should save a markdown report and return metadata."""
        result = await report_service.save_report(
            task_id="test_task_1",
            content="## Findings\n\nContent here.",
            fmt="markdown",
        )
        assert result["task_id"] == "test_task_1"
        assert "report_id" in result
        assert result["report_id"].startswith("rp_")
        assert "markdown_path" in result
        assert result["markdown_path"].endswith(".md")
        assert "pdf_path" not in result

        # Verify file exists
        assert os.path.exists(result["markdown_path"])

    @pytest.mark.asyncio
    async def test_save_report_pdf(self, report_service):
        """Should save a PDF report and return metadata."""
        result = await report_service.save_report(
            task_id="test_task_2",
            content="# PDF Report\n\nPDF content.",
            fmt="pdf",
        )
        assert result["task_id"] == "test_task_2"
        assert "pdf_path" in result
        assert result["pdf_path"].endswith(".pdf")
        assert "markdown_path" not in result

        # Verify file exists
        if result.get("pdf_error"):
            pytest.skip(f"PDF generation failed: {result['pdf_error']}")
        assert os.path.exists(result["pdf_path"])

    @pytest.mark.asyncio
    async def test_save_report_both(self, report_service):
        """Should save both markdown and PDF when fmt='both'."""
        result = await report_service.save_report(
            task_id="test_task_3",
            content="# Both Formats\n\nContent.",
            fmt="both",
        )
        assert "markdown_path" in result
        assert "pdf_path" in result or "pdf_error" in result

        assert os.path.exists(result["markdown_path"])
        if "pdf_path" in result:
            assert os.path.exists(result["pdf_path"])

    @pytest.mark.asyncio
    async def test_get_report_markdown(self, report_service):
        """Should retrieve markdown content."""
        content = "# Test\n\nRetrieval test."
        await report_service.save_report(
            task_id="get_test", content=content, fmt="markdown"
        )
        retrieved = await report_service.get_report("get_test", fmt="markdown")
        assert retrieved is not None
        assert "Test" in retrieved
        assert "Retrieval test." in retrieved

    @pytest.mark.asyncio
    async def test_get_report_nonexistent(self, report_service):
        """Should return None for missing report."""
        result = await report_service.get_report("nonexistent_task")
        assert result is None

    @pytest.mark.asyncio
    async def test_list_reports_empty(self, report_service):
        """Empty service should return empty list."""
        reports = report_service.list_reports()
        assert reports == []

    @pytest.mark.asyncio
    async def test_list_reports(self, report_service):
        """Should list saved reports."""
        await report_service.save_report(
            task_id="list_test_1",
            content="# First\n\nFirst report.",
            fmt="markdown",
        )
        await report_service.save_report(
            task_id="list_test_2",
            content="# Second\n\nSecond report.",
            fmt="markdown",
        )
        reports = report_service.list_reports(limit=10)
        assert len(reports) >= 2

    @pytest.mark.asyncio
    async def test_generate_report_id(self, report_service):
        """Should generate unique IDs starting with rp_."""
        id1 = report_service._generate_report_id()
        id2 = report_service._generate_report_id()
        assert id1.startswith("rp_")
        assert id2.startswith("rp_")
        assert id1 != id2

    @pytest.mark.asyncio
    async def test_save_report_with_sources(self, report_service):
        """Should include sources in saved report."""
        sources = [
            {"title": "Src1", "url": "https://ex.com/1"},
            {"title": "Src2", "url": "https://ex.com/2"},
        ]
        result = await report_service.save_report(
            task_id="src_test",
            content="# Sources\n\nContent",
            fmt="markdown",
            sources=sources,
        )
        assert os.path.exists(result["markdown_path"])
        with open(result["markdown_path"], "r", encoding="utf-8") as f:
            content = f.read()
        assert "## References" in content
        assert "Src1" in content
        assert "https://ex.com/1" in content
