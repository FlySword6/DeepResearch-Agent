"""BrowserTool — fetches and extracts text content from URLs.

Prefers headless Playwright (Chromium) so JavaScript-rendered pages and
PDFs are handled; falls back to httpx + BeautifulSoup when Playwright
is unavailable or fails.
"""

import asyncio
import io
import logging
import re
from typing import Any, Optional

import httpx
from bs4 import BeautifulSoup

from app.config import settings
from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

BROWSER_PARAMETERS = {
    "type": "object",
    "properties": {"url": {"type": "string", "description": "The URL to fetch"}},
    "required": ["url"],
}

MAX_CONTENT_CHARS = 8000
HTTP_TIMEOUT = 45
MAX_RETRIES = 3

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
]


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes via pypdf; graceful on failure."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(pdf_bytes))
        parts = [page.extract_text() or "" for page in reader.pages]
        return "\n\n".join(p for p in parts if p.strip())
    except Exception as exc:
        logger.warning("PDF text extraction failed: %s", exc)
        return "[PDF 文本提取失败]"


def _truncate(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", text.strip())
    truncated = text[:MAX_CONTENT_CHARS]
    if len(text) > MAX_CONTENT_CHARS:
        truncated += "\n\n[Content truncated]"
    return truncated


class BrowserTool(BaseTool):
    name = "browse"
    description = "Fetch and extract text content from a URL (JS-rendered pages and PDFs supported)"
    parameters = BROWSER_PARAMETERS

    _playwright_ok: Optional[bool] = None

    def _playwright_available(self) -> bool:
        """Lazy-check whether the playwright package is importable."""
        if BrowserTool._playwright_ok is None:
            try:
                import playwright  # noqa: F401

                BrowserTool._playwright_ok = True
            except Exception:
                logger.warning("Playwright not installed; using httpx fallback")
                BrowserTool._playwright_ok = False
        return BrowserTool._playwright_ok

    async def execute(self, url: str, **_kwargs: Any) -> ToolResult:
        if not url or not isinstance(url, str):
            return ToolResult(success=False, error="A valid 'url' string parameter is required.")

        if not url.startswith(("http://", "https://")):
            logger.warning("BrowserTool skipping non-HTTP URL: %s", url)
            return ToolResult(
                success=False,
                error="Not a valid HTTP URL.",
                data={"title": "Skipped", "content": "", "url": url},
                metadata={"skipped": True},
            )

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                if settings.BROWSER_USE_PLAYWRIGHT and self._playwright_available():
                    try:
                        return await self._fetch_with_playwright(url)
                    except Exception as exc:
                        logger.warning(
                            "Playwright fetch failed for %s, falling back to httpx: %s",
                            url, exc,
                        )
                return await self._fetch_and_extract(url, attempt)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "BrowserTool attempt %d/%d failed for %s: %s",
                    attempt + 1, MAX_RETRIES, url, exc,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(1.5 ** (attempt + 1))

        logger.exception("BrowserTool exhausted retries for URL: %s", url)
        return ToolResult(
            success=False,
            error=f"Failed to fetch {url} after {MAX_RETRIES} attempts: {last_exc}",
        )

    async def _fetch_with_playwright(self, url: str) -> ToolResult:
        """Fetch via headless Chromium; handles JS rendering and PDFs."""
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                page = await browser.new_page(user_agent=_USER_AGENTS[0])
                response = await page.goto(
                    url,
                    timeout=HTTP_TIMEOUT * 1000,
                    wait_until="domcontentloaded",
                )
                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception:
                    pass

                headers = response.headers if response else {}
                content_type = headers.get("content-type", "")
                title = await page.title() if page else ""

                if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
                    body = await response.body() if response else b""
                    text = _extract_pdf_text(body)
                else:
                    text = await page.evaluate("() => document.body ? document.body.innerText : ''")
                    if not text or not text.strip():
                        text = await page.content()

                truncated = _truncate(text)
                return ToolResult(
                    success=True,
                    data={"title": title or "", "content": truncated, "url": url},
                    metadata={
                        "content_type": content_type,
                        "content_length": len(text),
                        "truncated": len(text) > MAX_CONTENT_CHARS,
                        "engine": "playwright",
                    },
                )
            finally:
                await browser.close()

    async def _fetch_and_extract(self, url: str, attempt: int = 0) -> ToolResult:
        user_agent = _USER_AGENTS[attempt % len(_USER_AGENTS)]
        headers = {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
        }
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()

        content_type = response.headers.get("content-type", "")

        if "pdf" in content_type.lower() or url.lower().endswith(".pdf"):
            text = _extract_pdf_text(response.content)
            title = url.rsplit("/", 1)[-1]
            truncated = _truncate(text)
            return ToolResult(
                success=True,
                data={"title": title, "content": truncated, "url": url},
                metadata={
                    "content_type": content_type,
                    "content_length": len(text),
                    "truncated": len(text) > MAX_CONTENT_CHARS,
                    "engine": "httpx+pdf",
                },
            )

        html = response.text
        soup = BeautifulSoup(html, "html.parser")

        for tag in soup.find_all(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
            tag.decompose()

        title = soup.title.string.strip() if soup.title and soup.title.string else ""

        content_el = (
            soup.find("article")
            or soup.find("main")
            or soup.find('[role="main"]')
            or soup.find("body")
        )

        text = (
            content_el.get_text(separator="\n", strip=True)
            if content_el
            else soup.get_text(separator="\n", strip=True)
        )
        truncated = _truncate(text)

        return ToolResult(
            success=True,
            data={"title": title, "content": truncated, "url": url},
            metadata={
                "content_type": content_type,
                "content_length": len(text),
                "truncated": len(text) > MAX_CONTENT_CHARS,
                "engine": "httpx",
            },
        )
