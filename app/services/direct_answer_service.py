"""简单问题的直接联网搜索回答服务。"""

import json
import logging
from typing import Any, Dict, List

from app.config import settings
from app.services.config_service import get_active_config
from app.services.llm_service import LLMService
from app.tools.search import SearchTool
from app.utils.llm import LLMConfig
from app.workflow.events import emit

logger = logging.getLogger(__name__)


class DirectAnswerService:
    """用搜索结果直接回答简单问题。

    该服务不进入 Planner/Researcher/Writer/Reviewer 流程，只执行一次联网搜索，
    再让 LLM 基于搜索摘要生成短答案。LLM 不可用时会退回到搜索结果列表。
    """

    def __init__(self) -> None:
        self._search_tool = SearchTool()
        self._llm = LLMService(max_retries=1, retry_delay=0.5)

    async def answer(self, question: str) -> Dict[str, Any]:
        """执行直接搜索问答，返回报告文本和来源列表。"""
        max_results = getattr(settings, "DIRECT_SEARCH_MAX_RESULTS", 5)

        emit(
            "agent_status",
            agent="DirectSearch",
            status="running",
            detail="简单问题路线：联网搜索并生成直接答案",
        )
        emit("tool_call", tool="search", params={"query": question, "max_results": max_results})

        result = await self._search_tool.execute(query=question, max_results=max_results)
        emit(
            "tool_result",
            tool="search",
            status="completed" if result.success else "failed",
            result=str(result.data)[:500] if result.data else result.error or "",
        )

        if not result.success:
            fallback = self._format_fallback_answer(question, [], result.metadata)
            emit(
                "agent_status",
                agent="DirectSearch",
                status="completed",
                detail="直接搜索未获得可靠结果",
            )
            return {
                "report": f"{fallback}\n\n原因：{result.error or '搜索工具未返回有效结果'}",
                "sources": [],
                "review_score": 0.4,
                "review_feedback": "Direct search route; no reliable search result returned.",
            }

        sources = self._normalize_sources(result.data)
        fallback = self._format_fallback_answer(question, sources, result.metadata)
        report = await self._summarize_with_llm(question, sources, fallback)

        emit(
            "agent_status",
            agent="DirectSearch",
            status="completed",
            detail="直接答案生成完成",
        )

        return {
            "report": report,
            "sources": sources,
            "review_score": 1.0,
            "review_feedback": "Direct search route; skipped multi-agent review.",
        }

    async def _summarize_with_llm(
        self,
        question: str,
        sources: List[Dict[str, str]],
        fallback: str,
    ) -> str:
        """让 LLM 基于搜索结果生成简短答案，失败时返回兜底内容。"""
        active_config = get_active_config()
        if not active_config.api_key:
            return fallback

        config = LLMConfig(
            provider=active_config.provider,
            model=active_config.model,
            base_url=active_config.base_url,
            temperature=0.2,
            max_tokens=1200,
        )

        system_prompt = (
            "你是一个简洁可靠的联网问答助手。只依据给定搜索结果回答；"
            "如果搜索结果不足以确定答案，要明确说明不确定。"
            "答案用中文，先给结论，再给必要依据，最后列出来源。"
        )
        user_prompt = (
            f"用户问题：{question}\n\n"
            "搜索结果 JSON：\n"
            f"{json.dumps(sources, ensure_ascii=False, indent=2)}"
        )

        return await self._llm.call_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_response=fallback,
            config=config,
        )

    def _normalize_sources(self, data: Any) -> List[Dict[str, str]]:
        """把 SearchTool 的返回值整理成报告可引用的来源列表。"""
        if not isinstance(data, list):
            return []

        sources: List[Dict[str, str]] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            title = str(item.get("title") or "Untitled").strip()
            url = str(item.get("url") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            source = str(item.get("source") or "web").strip()
            if not title and not url and not snippet:
                continue
            sources.append({
                "title": title,
                "url": url,
                "snippet": snippet[:800],
                "source": source,
            })
        return sources

    def _format_fallback_answer(
        self,
        question: str,
        sources: List[Dict[str, str]],
        metadata: Dict[str, Any],
    ) -> str:
        """LLM 不可用时的可读兜底答案。"""
        if not sources:
            return (
                "# 直接搜索结果\n\n"
                f"问题：{question}\n\n"
                "暂时没有搜索到可用结果，请换一个更具体的问法再试。"
            )

        source_name = metadata.get("source", "web") if isinstance(metadata, dict) else "web"
        lines = [
            "# 直接搜索结果",
            "",
            f"问题：{question}",
            "",
            f"已通过 {source_name} 完成联网搜索。当前 LLM 不可用，先返回可参考的搜索摘要：",
            "",
        ]
        for index, item in enumerate(sources, start=1):
            title = item.get("title") or f"来源 {index}"
            url = item.get("url") or ""
            snippet = item.get("snippet") or "无摘要"
            if url:
                lines.append(f"{index}. [{title}]({url})")
            else:
                lines.append(f"{index}. {title}")
            lines.append(f"   {snippet}")
        return "\n".join(lines)
