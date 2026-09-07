"""SearchTool：多搜索源并行聚合工具。

搜索源由 app.tools.search_backends 注册和创建。工具只返回真实来源结果；
除非显式开启 ENABLE_MOCK_SEARCH，否则不会把 mock 占位数据注入研究报告。
"""

import asyncio
import logging
from typing import Any, Dict, List

from app.config import settings
from app.tools.base import BaseTool, ToolResult
from app.tools.search_backends import build_backends

logger = logging.getLogger(__name__)

SEARCH_PARAMETERS = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "搜索查询语句"},
        "max_results": {"type": "integer", "description": "每个搜索源返回的最大结果数", "default": 5},
    },
    "required": ["query"],
}


class SearchTool(BaseTool):
    """并行调用多个搜索后端，合并、去重并返回真实结果。"""

    name = "search"
    description = "根据查询词搜索网页信息，并聚合 Tavily、DuckDuckGo、GitHub、Exa 等结果"
    parameters = SEARCH_PARAMETERS

    def __init__(self):
        self._backends = build_backends()

    async def execute(self, query: str, max_results: int = 5, **_kwargs: Any) -> ToolResult:
        """并行运行所有配置的搜索后端。"""
        query = (query or "").strip()
        if not query:
            return ToolResult(success=False, error="搜索查询不能为空", metadata={"source": "none", "result_count": 0})

        if not self._backends:
            return self._empty_result("未配置可用搜索后端，请检查 SEARCH_BACKENDS 或 API Key。")

        tasks = [backend.search(query, max_results) for backend in self._backends]
        result_lists = await asyncio.gather(*tasks, return_exceptions=True)

        all_results = self._dedupe_results(result_lists)
        if not all_results:
            if settings.ENABLE_MOCK_SEARCH:
                mock = await self._mock_results(query, max_results)
                return ToolResult(success=True, data=mock, metadata={"source": "mock", "result_count": len(mock)})
            backend_names = ",".join(backend.name for backend in self._backends)
            return self._empty_result(f"搜索后端没有返回真实结果，已跳过 mock 占位数据。后端: {backend_names}")

        source_order = {"tavily": 0, "exa": 1, "github": 2, "duckduckgo": 3}
        all_results.sort(key=lambda item: source_order.get(str(item.get("source", "")), 99))
        limit = max(1, max_results)
        all_results = all_results[:limit]

        return ToolResult(
            success=True,
            data=all_results,
            metadata={
                "source": ",".join(sorted(set(str(item.get("source", "?")) for item in all_results))),
                "result_count": len(all_results),
            },
        )

    def _dedupe_results(self, result_lists: List[Any]) -> List[Dict[str, Any]]:
        """收集成功结果，并按 URL 或标题去重。"""
        output: List[Dict[str, Any]] = []
        seen = set()
        for results in result_lists:
            if isinstance(results, Exception):
                logger.warning("Search backend failed: %s", results)
                continue
            if not isinstance(results, list):
                continue
            for item in results:
                if not isinstance(item, dict):
                    continue
                url = str(item.get("url") or "").strip()
                title = str(item.get("title") or "").strip()
                snippet = str(item.get("snippet") or "").strip()
                if not url and not title and not snippet:
                    continue
                key = url or title.lower()
                if key in seen:
                    continue
                seen.add(key)
                output.append({
                    "title": title,
                    "url": url,
                    "snippet": snippet,
                    "source": str(item.get("source") or "web"),
                })
        return output

    @staticmethod
    def _empty_result(message: str) -> ToolResult:
        logger.warning(message)
        return ToolResult(
            success=False,
            error=message,
            data=[],
            metadata={"source": "none", "result_count": 0},
        )

    async def _mock_results(self, query: str, max_results: int) -> List[Dict[str, str]]:
        """开发调试用 mock 结果；默认关闭。"""
        return [
            {
                "title": f"Mock result {index + 1}: {query}",
                "url": f"https://example.com/results/{index + 1}",
                "snippet": f"Mock search result for '{query}'.",
                "source": "mock",
            }
            for index in range(max_results)
        ]
