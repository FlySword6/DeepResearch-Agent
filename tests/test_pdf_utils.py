"""Tests for PDF generation utilities."""

import os
import tempfile
import pytest

from app.utils.pdf_utils import generate_pdf, generate_pdf_from_html


class TestGeneratePdf:
    """Tests for generate_pdf()."""

    @pytest.mark.asyncio
    async def test_generate_pdf_from_markdown(self, tmp_path):
        """Should produce a valid PDF file from markdown content."""
        md_content = """# Test Report

## Introduction
This is a test paragraph.

- Item 1
- Item 2

**Bold text** and *italic text*.
"""
        output_path = os.path.join(str(tmp_path), "test_output.pdf")
        result_path = await generate_pdf(markdown_content=md_content, output_path=output_path)

        assert result_path == output_path
        assert os.path.exists(output_path), "PDF file should exist"
        assert os.path.getsize(output_path) > 100, "PDF should have meaningful content"

    @pytest.mark.asyncio
    async def test_generate_pdf_with_code_block(self, tmp_path):
        """Should handle code blocks in PDF generation."""
        md = """# Code Example

```python
def hello():
    print("world")
```
"""
        output_path = os.path.join(str(tmp_path), "code_test.pdf")
        await generate_pdf(md, output_path)
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 100

    @pytest.mark.asyncio
    async def test_generate_pdf_with_empty_content(self, tmp_path):
        """Should handle minimal content."""
        output_path = os.path.join(str(tmp_path), "empty.pdf")
        result = await generate_pdf("# Minimal", output_path)
        assert result == output_path
        assert os.path.exists(output_path)

    @pytest.mark.asyncio
    async def test_generate_pdf_creates_directory(self, tmp_path):
        """Should create parent directories if they don't exist."""
        nested_path = os.path.join(str(tmp_path), "nested", "sub", "report.pdf")
        result = await generate_pdf("# Nested", nested_path)
        assert result == nested_path
        assert os.path.exists(nested_path)

    @pytest.mark.asyncio
    async def test_generate_pdf_with_list(self, tmp_path):
        """Should handle ordered and unordered lists."""
        md = """# List Test

- First item
- Second item
- Third item

1. Ordered one
2. Ordered two
"""
        output_path = os.path.join(str(tmp_path), "lists.pdf")
        await generate_pdf(md, output_path)
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 100


class TestGeneratePdfFromHtml:
    """Tests for generate_pdf_from_html()."""

    @pytest.mark.asyncio
    async def test_generate_from_simple_html(self, tmp_path):
        """Should convert HTML to PDF."""
        html = "<h1>Hello</h1><p>World</p>"
        output_path = os.path.join(str(tmp_path), "from_html.pdf")
        await generate_pdf_from_html(html, output_path)
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 100

    @pytest.mark.asyncio
    async def test_generate_from_complex_html(self, tmp_path):
        """Should handle more complex HTML structures."""
        html = """
        <h1>Title</h1>
        <h2>Section</h2>
        <p>Paragraph with <strong>bold</strong> and <em>italic</em>.</p>
        <ul>
            <li>Item A</li>
            <li>Item B</li>
        </ul>
        """
        output_path = os.path.join(str(tmp_path), "complex.pdf")
        await generate_pdf_from_html(html, output_path)
        assert os.path.exists(output_path)
        assert os.path.getsize(output_path) > 100
