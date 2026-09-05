"""Context budget utilities for the writer."""

from typing import Any, Dict, List


def truncate_research_context(
    research_data: List[Dict[str, Any]], max_chars: int = 60000
) -> List[Dict[str, Any]]:
    """Keep summaries and bounded raw results within a total char budget.

    Each item keeps its summary; raw_result is capped at 2000 chars.
    Once the budget is exhausted, remaining items are dropped.
    """
    out: List[Dict[str, Any]] = []
    remaining = max_chars
    for item in research_data:
        summary = str(item.get("summary", ""))
        raw = str(item.get("raw_result", ""))[:2000]
        text = f"{summary}\n{raw}"
        if len(text) > remaining and remaining > 0:
            summary = summary[:remaining]
            raw = ""
        remaining = max(0, remaining - len(summary) - len(raw))
        out.append({**item, "summary": summary, "raw_result": raw})
        if remaining == 0:
            break
    return out
