"""Citation validation utilities: extract and verify [来源: title](url) citations."""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import List, Tuple

import httpx

logger = logging.getLogger(__name__)

CITATION_RE = re.compile(r"\[来源:\s*([^\]]+)\]\((https?://[^)\s]+)\)")


@dataclass
class Citation:
    title: str
    url: str


@dataclass
class CitationCheck:
    title: str
    url: str
    valid: bool
    status: int = 0
    error: str = ""


def extract_citations(report: str) -> List[Citation]:
    return [
        Citation(title=m.group(1).strip(), url=m.group(2).rstrip(".,;"))
        for m in CITATION_RE.finditer(report)
    ]


async def _check_one(url: str, timeout: float = 10.0) -> Tuple[int, str]:
    """Return (status, error). status != 0 and < 400 means reachable."""
    headers = {"User-Agent": "Mozilla/5.0 (DeepResearch-Agent citation-validator)"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        try:
            resp = await client.head(url)
        except (httpx.HTTPError, httpx.TimeoutException):
            try:
                resp = await client.get(url)
            except (httpx.HTTPError, httpx.TimeoutException) as exc:
                return 0, f"请求失败: {type(exc).__name__}"
        if resp.status_code >= 400:
            return resp.status_code, f"HTTP {resp.status_code}"
        return resp.status_code, ""


async def validate_citations(
    citations: List[Citation], max_workers: int = 8
) -> List[CitationCheck]:
    """Check each citation URL's reachability with bounded concurrency."""
    sem = asyncio.Semaphore(max_workers)

    async def check(c: Citation) -> CitationCheck:
        async with sem:
            status, error = await _check_one(c.url)
            return CitationCheck(
                title=c.title,
                url=c.url,
                valid=status != 0 and status < 400,
                status=status,
                error=error,
            )

    return list(await asyncio.gather(*(check(c) for c in citations)))


def render_validation_section(checks: List[CitationCheck]) -> str:
    """Render a '引用核验' section appended to the final report."""
    if not checks:
        return ""
    valid = [c for c in checks if c.valid]
    invalid = [c for c in checks if not c.valid]
    lines = [
        "",
        "---",
        "## 引用核验",
        "",
        f"共核验 {len(checks)} 条引用，其中 {len(valid)} 条可达，{len(invalid)} 条无法访问。",
    ]
    if invalid:
        lines += ["", "以下引用无法访问，请谨慎使用：", ""]
        for c in invalid:
            reason = c.error or f"HTTP {c.status}"
            lines.append(f"- [{c.title}]({c.url}) — {reason}")
    return "\n".join(lines)
