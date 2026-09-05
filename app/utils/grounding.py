"""Claim-evidence grounding checks (PING-style hallucination audit)."""

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Callable, List, Optional

import httpx

logger = logging.getLogger(__name__)

BULLET_RE = re.compile(r"(?m)^\s*[-*]\s*(.+)$")
CITATION_RE = re.compile(r"\[来源:\s*([^\]]+)\]\((https?://[^)\s]+)\)")
_STOPWORDS = frozenset(
    {"的", "了", "是", "在", "和", "与", "及", "或", "对", "为", "这", "那", "有", "将", "以及", "等", "中", "上", "下"}
)


@dataclass
class ClaimCheck:
    claim: str
    url: str
    supported: bool
    reason: str = ""


def _tokenize(text: str) -> set:
    tokens = set(re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower()))
    return tokens - _STOPWORDS


async def _fetch(url: str, timeout: float = 10.0) -> str:
    headers = {"User-Agent": "Mozilla/5.0 (DeepResearch-Agent grounding-check)"}
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text[:4000]


def _overlap_supported(claim: str, page_text: str, threshold: float = 0.35) -> bool:
    claim_tokens = _tokenize(claim)
    if not claim_tokens:
        return False
    page_tokens = _tokenize(page_text)
    if not page_tokens:
        return False
    hit = len(claim_tokens & page_tokens)
    return hit / len(claim_tokens) >= threshold


def extract_claims_with_citations(report: str) -> List[ClaimCheck]:
    checks = []
    for m in BULLET_RE.finditer(report):
        line = m.group(1)
        cites = CITATION_RE.findall(line)
        if not cites:
            continue
        claim = CITATION_RE.sub("", line).strip(" :：,，")
        for _title, url in cites:
            if claim:
                checks.append(ClaimCheck(claim=claim, url=url, supported=False))
    return checks


class GroundingChecker:
    def __init__(self, fetch: Optional[Callable] = None, threshold: float = 0.35):
        self._fetch = fetch or _fetch
        self.threshold = threshold

    async def check_report(self, report: str) -> List[ClaimCheck]:
        checks = extract_claims_with_citations(report)
        sem = asyncio.Semaphore(8)

        async def check(c: ClaimCheck) -> ClaimCheck:
            async with sem:
                try:
                    page_text = await self._fetch(c.url)
                    supported = _overlap_supported(c.claim, page_text, self.threshold)
                    reason = (
                        "页面包含与论断重叠的关键词"
                        if supported
                        else "页面未包含支撑该论断的关键内容"
                    )
                except Exception as exc:
                    supported = False
                    reason = f"页面获取失败: {type(exc).__name__}"
                return ClaimCheck(
                    claim=c.claim, url=c.url, supported=supported, reason=reason
                )

        return list(await asyncio.gather(*(check(c) for c in checks)))


def render_evidence_table(checks: List[ClaimCheck]) -> str:
    if not checks:
        return ""
    rows = [
        "",
        "---",
        "## 论断-证据核验",
        "",
        "| # | 论断 | 来源 | 结论 |",
        "|---|------|------|------|",
    ]
    for i, c in enumerate(checks, 1):
        rows.append(
            f"| {i} | {c.claim[:60]} | [{c.url[:40]}]({c.url}) | "
            f"{'✅ 有支撑' if c.supported else '⚠️ 无支撑'} |"
        )
    unsupported = [c for c in checks if not c.supported]
    if unsupported:
        rows += ["", "以下论断缺少证据支撑，请在报告中修正或标注不确定性：", ""]
        for c in unsupported:
            rows.append(f"- {c.claim[:80]}（{c.reason}）")
    return "\n".join(rows)
