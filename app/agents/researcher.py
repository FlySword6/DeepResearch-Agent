"""ResearcherAgent - executes subtasks using tools, auto-browses search results, extracts insights with citations."""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.models.state import ResearchState
from app.tools.router import ToolRouter
from app.utils.llm import LLMConfig, llm_call, resolve_model

logger = logging.getLogger(__name__)


class ResearcherAgent(BaseAgent):
    """
    ResearcherAgent executes research subtasks by calling the appropriate tool,
    analyzes results, and extracts key insights with source citations.

    For 'search' subtasks it additionally browses the top result URLs and
    attaches source metadata so that downstream writer can produce cited reports.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 4096,
    ):
        super().__init__(model_name, temperature, max_tokens)

    def system_prompt(self) -> str:
        from app.utils.date_hint import today_hint

        return f"""{today_hint()}

你是一名研究分析师。请调用工具执行研究子任务，分析结果并提取关键见解。

请用中文以 2-4 个简洁的要点总结核心发现。要点应聚焦于：
- 重要的事实、数据点和统计数字
- 关键名称、日期和组织
- 与原始研究问题的直接相关性

【重要】每个要点末尾必须注明信息来源，使用格式：[来源: 网站名称](URL)
如果信息来自搜索结果 snippet，注明搜索引擎即可。如果来自浏览的页面内容，注明页面标题和 URL。

每个要点控制在 100 字以内，要求具体、有依据。"""

    async def invoke(self, state: ResearchState, tools=None) -> Dict[str, Any]:
        """Execute the current subtask (kept for single-step callers)."""
        if state.current_step >= len(state.plan):
            return {}
        entry, new_sources = await self.execute_step(state, state.current_step, tools)
        return {
            "research_data": list(state.research_data) + [entry],
            "sources": list(state.sources) + new_sources,
            "current_step": state.current_step + 1,
        }

    async def execute_step(self, state, step_index: int, tools=None):
        """Execute one subtask; returns (result_entry, new_sources)."""
        if step_index >= len(state.plan):
            return {}, []
        current_task = state.plan[step_index]
        tool_name = ToolRouter.resolve_tool_name(current_task.tool)
        try:
            if tool_name == "search":
                return await self._execute_search_with_browse(
                    state, current_task, tools, step_index=step_index
                )
            if tool_name == "browse" and not _extract_url(current_task.description):
                logger.info(
                    "Browse task has no URL; rerouting to search: %s",
                    current_task.description,
                )
                return await self._execute_search_with_browse(
                    state, current_task, tools, step_index=step_index
                )
            return await self._execute_regular_tool(
                state, current_task, tool_name, tools, step_index=step_index
            )
        except Exception as exc:
            logger.exception("Researcher step %d failed", step_index)
            entry = {
                "step": step_index,
                "task_id": current_task.id,
                "description": current_task.description,
                "tool": tool_name,
                "raw_result": f"Error: {exc}",
                "summary": f"子任务执行失败: {exc}",
            }
            return entry, []

    # ------------------------------------------------------------------
    # Search + auto-browse (the big improvement)
    # ------------------------------------------------------------------

    async def _execute_search_with_browse(
        self, state, current_task, tools, step_index=None
    ):
        """Execute a search, then auto-browse top URLs; returns (entry, sources)."""
        params = {"query": current_task.description, "max_results": 5}
        raw_result, tool_success, tool_metadata = await self._run_tool(
            tools, "search", params, workspace_dir=getattr(state, "workspace_dir", "")
        )

        if not tool_success:
            summarized = self._format_tool_failure(current_task.description, raw_result)
            return {
                "step": step_index if step_index is not None else state.current_step,
                "task_id": current_task.id,
                "description": current_task.description,
                "tool": "search",
                "raw_result": raw_result,
                "summary": summarized,
                "source_count": 0,
                "success": False,
            }, []

        if self._is_mock_search_result(raw_result, tool_metadata):
            summarized = self._format_tool_failure(
                current_task.description,
                "搜索返回 mock 占位数据，已忽略。",
            )
            return {
                "step": step_index if step_index is not None else state.current_step,
                "task_id": current_task.id,
                "description": current_task.description,
                "tool": "search",
                "raw_result": [],
                "summary": summarized,
                "source_count": 0,
                "success": False,
            }, []

        search_items = raw_result if isinstance(raw_result, list) else []

        new_sources = []
        for item in search_items:
            url = item.get("url", "")
            title = item.get("title", "")
            snippet = item.get("snippet", "")
            source_type = item.get("source", "web")
            if url and source_type != "mock":
                new_sources.append({
                    "url": url,
                    "title": title or url,
                    "snippet": (snippet or "")[:300],
                    "source": source_type,
                })

        real_urls = [
            s for s in new_sources
            if s["url"].startswith(("http://", "https://"))
        ]
        top_urls = real_urls[:3]

        browse_contents = []
        if top_urls and tools is not None:
            browse_tasks = [tools.execute("browse", url=s["url"]) for s in top_urls]
            browse_responses = await asyncio.gather(*browse_tasks, return_exceptions=True)
            for i, response in enumerate(browse_responses):
                if isinstance(response, Exception):
                    browse_contents.append(f"*Failed to browse {top_urls[i]['title']}: {response}*")
                elif response.success:
                    data = response.data or {}
                    content = (data.get("content") or "")[:2500]
                    title = data.get("title", top_urls[i]["title"])
                    url = data.get("url", top_urls[i]["url"])
                    browse_contents.append(f"**来源: [{title}]({url})**\n{content}")
                else:
                    browse_contents.append(f"*Failed to browse: {response.error}*")

        combined_parts = ["## 搜索结果"]
        for item in search_items:
            t = item.get("title", "")
            u = item.get("url", "")
            s = item.get("snippet", "")
            src = item.get("source", "?")
            combined_parts.append(f"- **[{t}]({u})** ({src}): {s[:300]}")

        if browse_contents:
            combined_parts.append("\n## 详细页面内容")
            combined_parts.extend(browse_contents)

        combined_raw = "\n\n".join(combined_parts)

        try:
            summarized = await self._summarize_result(
                current_task,
                combined_raw,
                "search+browse",
                task_text=state.task,
                profile_id=getattr(state, "profile_id", None),
            )
        except Exception as exc:
            logger.warning(f"ResearcherAgent LLM summarization failed: {exc}")
            summarized = self._fallback_summary(combined_raw)

        result_entry = {
            "step": step_index if step_index is not None else state.current_step,
            "task_id": current_task.id,
            "description": current_task.description,
            "tool": "search+browse",
            "raw_result": combined_raw[:8000],
            "summary": summarized,
            "source_count": len(new_sources),
            "success": True,
        }
        return result_entry, new_sources

    # ------------------------------------------------------------------
    # Regular (non-search) tool execution
    # ------------------------------------------------------------------

    async def _execute_regular_tool(
        self, state, current_task, tool_name, tools, step_index=None
    ):
        """Execute a non-search subtask; returns (entry, sources)."""
        params = self._build_params(tool_name, current_task)
        raw_result, tool_success, tool_metadata = await self._run_tool(
            tools, tool_name, params, workspace_dir=getattr(state, "workspace_dir", "")
        )

        if not tool_success:
            summarized = self._format_tool_failure(current_task.description, raw_result)
        elif tool_name == "rag" and self._is_mock_search_result(raw_result, tool_metadata):
            summarized = self._format_tool_failure(current_task.description, "RAG 返回占位数据，已忽略。")
            raw_result = {}
            tool_success = False
        else:
            try:
                summarized = await self._summarize_result(
                    current_task,
                    str(raw_result),
                    tool_name,
                    task_text=state.task,
                    profile_id=getattr(state, "profile_id", None),
                )
            except Exception as exc:
                logger.warning(f"ResearcherAgent LLM summarization failed: {exc}")
                summarized = self._fallback_summary(raw_result)

        new_sources = self._extract_sources(raw_result, tool_name)

        result_entry = {
            "step": step_index if step_index is not None else state.current_step,
            "task_id": current_task.id,
            "description": current_task.description,
            "tool": tool_name,
            "raw_result": str(raw_result)[:5000],
            "summary": summarized,
            "success": tool_success,
        }
        return result_entry, new_sources

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _run_tool(self, tools, tool_name: str, params: dict, workspace_dir: str = "") -> tuple[Any, bool, Dict[str, Any]]:
        """Execute a tool and return (data_or_error, success, metadata)."""
        if tools is None:
            return f"Error: No ToolRouter available for '{tool_name}'.", False, {}
        try:
            if tool_name in ("analyze", "read_workspace"):
                params = {**params, "workspace_dir": workspace_dir}
            result = await tools.execute(tool_name, **params)
            return (
                result.data if result.success else f"Error: {result.error}",
                result.success,
                result.metadata or {},
            )
        except Exception as exc:
            logger.exception("ResearcherAgent tool execution failed for '%s'", tool_name)
            return f"Error: {exc}", False, {}

    @staticmethod
    def _build_params(tool_name: str, current_task) -> dict:
        """Build parameter dict for a non-search tool."""
        if tool_name == "browse":
            url = _extract_url(current_task.description)
            return {"url": url if url else current_task.description}
        if tool_name == "analyze":
            return {
                "code": _generate_analysis_code(current_task.description),
                "timeout": 30,
            }
        if tool_name == "rag":
            return {"action": "retrieve", "query": current_task.description, "k": 5}
        if tool_name == "read_workspace":
            filename = _extract_filename(current_task.description)
            return {"filename": filename if filename else current_task.description}
        return {}

    @staticmethod
    def _extract_sources(raw_result: Any, tool_name: str) -> List[Dict[str, str]]:
        """Extract source metadata from a tool result."""
        sources = []
        if tool_name == "browse" and isinstance(raw_result, dict):
            url = raw_result.get("url", "")
            title = raw_result.get("title", "")
            if url and url.startswith(("http://", "https://")):
                sources.append({"url": url, "title": title or url, "snippet": "", "source": "browse"})
        return sources

    async def _summarize_result(
        self,
        task,
        result_data: str,
        tool_name: str = "",
        task_text: str = "",
        profile_id: Optional[str] = None,
    ) -> str:
        """Use LLM to summarize tool results with citation instructions."""
        from app.services.skill_service import enrich_prompt

        config = LLMConfig(
            model=resolve_model(self.model_name),
            temperature=0.3,
            max_tokens=1024,
        )
        result_str = str(result_data)
        if len(result_str) > 6000:
            result_str = result_str[:6000] + "\n...[truncated]"

        user_prompt = (
            f"研究子任务: {task.description}\n\n"
            f"使用的工具: {tool_name}\n\n"
            f"工具返回结果:\n{result_str}\n\n"
            "请用中文以 2-4 个要点总结关键发现。\n"
            "【重要】每个要点末尾必须注明信息来源，例如：[来源: 维基百科](https://...)"
        )
        effective_task = task_text or task.description
        extra_context = task.description if task_text else task_text
        enriched_prompt = await enrich_prompt(
            self.system_prompt(),
            "researcher",
            effective_task,
            profile_id,
            extra_context=extra_context,
        )
        response = await llm_call(
            system_prompt=enriched_prompt,
            user_prompt=user_prompt,
            config=config,
        )
        return response.strip()

    @staticmethod
    def _fallback_summary(result_data: Any) -> str:
        """Generate a basic summary without LLM.

        Handles JSON search results, dict outputs from browse/analyze, and plain text.
        """
        # JSON array of search results
        if isinstance(result_data, list):
            out = []
            for item in result_data[:5]:
                t = item.get("title", "")
                u = item.get("url", "")
                s = item.get("snippet", "") or item.get("content", "")
                src = item.get("source", "")
                if t:
                    out.append(f"**{t}**")
                if u:
                    out.append(f"链接: {u}")
                if src:
                    out.append(f"来源: {src}")
                if s:
                    out.append(str(s)[:300])
                out.append("")
            return "\n".join(out) if out else str(result_data)[:500]

        # Dict with stdout (analyze tool)
        if isinstance(result_data, dict):
            if "stdout" in result_data:
                return result_data.get("stdout", str(result_data))[:500]
            if "results" in result_data:
                out = []
                for item in result_data.get("results", [])[:5]:
                    metadata = item.get("metadata", {}) or {}
                    source = metadata.get("source", "")
                    score = item.get("score", item.get("rrf_score", 0.0))
                    text = str(item.get("text", ""))[:500]
                    matched = item.get("matched_children", []) or []
                    if source:
                        out.append(f"[来源: {source}] score={score:.4f}")
                    if matched:
                        out.append("命中片段: " + str(matched[0])[:240])
                    if text:
                        out.append(text)
                    out.append("")
                return "\n".join(out).strip() if out else str(result_data)[:500]
            if "content" in result_data:
                content = str(result_data["content"])[:300]
                url = result_data.get("url", "")
                return f"来源: [{result_data.get('title', '')}]({url})\n{content}" if url else content[:500]
            parts = []
            for k, v in result_data.items():
                if v and k not in ("execution_time", "stderr"):
                    parts.append(f"{k}: {str(v)[:200]}")
            return "\n".join(parts) if parts else str(result_data)[:500]

        # Plain text
        result_str = str(result_data)
        if len(result_str) > 500:
            result_str = result_str[:500] + "..."
        return result_str

    @staticmethod
    def _is_mock_search_result(result_data: Any, metadata: Dict[str, Any]) -> bool:
        """Detect mock results so placeholder data never becomes report evidence."""
        if metadata.get("source") == "mock":
            return True
        if isinstance(result_data, list):
            return any(isinstance(item, dict) and item.get("source") == "mock" for item in result_data)
        return False

    @staticmethod
    def _format_tool_failure(description: str, raw_result: Any) -> str:
        """Format tool failure as explicit non-evidence."""
        message = str(raw_result).replace("Error:", "").strip()
        return (
            f"- 子任务「{description}」未获得可用外部资料。\n"
            f"- 原因：{message or '工具未返回有效结果'}。\n"
            "- 该步骤不会作为事实依据写入结论，建议补充可用搜索 API Key、上传参考文件或提供明确 URL。"
        )


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------

def _extract_url(description: str) -> Optional[str]:
    """Extract a URL from the subtask description if present."""
    url_pattern = r"https?://[^\s,;]+"
    match = re.search(url_pattern, description)
    return match.group(0) if match else None


def _extract_filename(description: str) -> Optional[str]:
    """Extract a workspace filename from the subtask description if present.

    Looks for a quoted filename or a word ending in a common document
    extension (md, txt, csv, json, pdf, docx).
    """
    quoted = re.search(r"['\"]?([A-Za-z0-9_\-.一-鿿]+\.(?:md|txt|csv|json|pdf|docx))['\"]?", description)
    return quoted.group(1) if quoted else None


def _generate_analysis_code(description: str) -> str:
    """Generate basic analysis Python code based on the description."""
    return f'''"""
Analysis task: {description}
"""
import json

data = {{
    "task": "{description}",
    "findings": []
}}

print(json.dumps(data, indent=2))
print("Analysis complete for: {description}")
'''
