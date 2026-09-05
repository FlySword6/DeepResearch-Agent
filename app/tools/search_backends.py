"""可插拔搜索后端。

SearchTool 只负责调度和去重，具体搜索源放在这里，方便后续按配置增删
Tavily、DuckDuckGo、GitHub、Exa 等后端。
"""

import asyncio
import logging
from typing import Any, Dict, List, Protocol

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class SearchBackend(Protocol):
    """搜索后端协议。"""

    name: str

    async def search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """执行搜索并返回统一结构的结果列表。"""
        ...


class TavilyBackend:
    """Tavily 搜索后端，适合通用网页搜索和研究型问题。"""

    name = "tavily"

    async def search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        api_key = settings.TAVILY_API_KEY
        if not api_key:
            return []

        from tavily import TavilyClient

        client = TavilyClient(api_key=api_key)
        response = await asyncio.to_thread(
            client.search,
            query=query,
            search_depth="advanced",
            max_results=max_results,
        )
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": item.get("content", item.get("snippet", "")),
                "source": self.name,
            }
            for item in response.get("results", [])
            if item.get("url") or item.get("content") or item.get("snippet")
        ]


class DuckDuckGoBackend:
    """DuckDuckGo 免费搜索后端。"""

    name = "duckduckgo"

    async def search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            logger.warning("duckduckgo_search not installed")
            return []

        def _search() -> List[Dict[str, Any]]:
            return list(DDGS().text(query, max_results=max_results))

        results = await asyncio.to_thread(_search)
        return [
            {
                "title": item.get("title", ""),
                "url": item.get("href", item.get("link", "")),
                "snippet": item.get("body", item.get("snippet", "")),
                "source": self.name,
            }
            for item in results
            if item.get("href") or item.get("link") or item.get("body") or item.get("snippet")
        ]


class GitHubBackend:
    """GitHub 仓库搜索后端，适合技术框架、开源项目和代码生态问题。"""

    name = "github"

    async def search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        headers = {"Accept": "application/vnd.github.v3+json"}
        token = settings.GITHUB_TOKEN or ""
        if token:
            headers["Authorization"] = f"token {token}"

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.github.com/search/repositories",
                    params={"q": query, "per_page": max_results, "sort": "stars"},
                    headers=headers,
                )
                if response.status_code != 200:
                    logger.warning("GitHub search returned %d: %s", response.status_code, response.text[:200])
                    return []

                output: List[Dict[str, Any]] = []
                for repo in response.json().get("items", [])[:max_results]:
                    desc = repo.get("description") or ""
                    lang = repo.get("language") or ""
                    stars = repo.get("stargazers_count", 0)
                    snippet = f"[{lang}] {desc}" if lang else desc
                    if stars:
                        snippet = f"{stars} stars. {snippet}" if snippet else f"{stars} stars"
                    output.append(
                        {
                            "title": repo.get("full_name", repo.get("name", "")),
                            "url": repo.get("html_url", ""),
                            "snippet": snippet[:500],
                            "source": self.name,
                        }
                    )
                return output
        except Exception as exc:
            logger.warning("GitHub search failed: %s", exc)
            return []


class ExaBackend:
    """Exa 搜索后端，可选启用，适合研究型网页检索。"""

    name = "exa"

    async def search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        api_key = getattr(settings, "EXA_API_KEY", None)
        if not api_key:
            return []

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                "https://api.exa.ai/search",
                headers={"x-api-key": api_key, "Content-Type": "application/json"},
                json={"query": query, "numResults": max_results, "contents": {"text": True}},
            )
            response.raise_for_status()

        return [
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "snippet": (item.get("text") or item.get("summary") or "")[:800],
                "source": self.name,
            }
            for item in response.json().get("results", [])
            if item.get("url") or item.get("text") or item.get("summary")
        ]


BACKEND_REGISTRY: Dict[str, type] = {
    "tavily": TavilyBackend,
    "duckduckgo": DuckDuckGoBackend,
    "github": GitHubBackend,
    "exa": ExaBackend,
}


def build_backends() -> List[SearchBackend]:
    """按 SEARCH_BACKENDS 配置创建搜索后端列表。"""
    names = [
        name.strip().lower()
        for name in settings.SEARCH_BACKENDS.split(",")
        if name.strip()
    ]
    backends: List[SearchBackend] = []
    for name in names:
        backend_cls = BACKEND_REGISTRY.get(name)
        if backend_cls is None:
            logger.warning("Unknown search backend: %s", name)
            continue
        try:
            backends.append(backend_cls())
        except Exception as exc:
            logger.warning("Failed to init search backend %s: %s", name, exc)
    return backends
