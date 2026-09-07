"""简单问题的直接联网搜索回答服务。"""

import json
import logging
import re
from typing import Any, Dict, List

import httpx

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

        weather_answer = await self._answer_weather(question)
        if weather_answer is not None:
            return weather_answer

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

        answer = await self._llm.call_with_fallback(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_response=fallback,
            config=config,
        )
        if answer and answer.strip():
            return answer

        logger.warning("Direct answer LLM returned empty content, using search fallback")
        return fallback

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

    async def _answer_weather(self, question: str) -> Dict[str, Any] | None:
        """对天气类简单问题走专用实时天气接口，避免搜索摘要不稳定。"""
        if not self._is_weather_question(question):
            return None

        city = self._extract_weather_city(question)
        if not city:
            return None

        emit(
            "agent_status",
            agent="Weather",
            status="running",
            detail=f"天气问题路线：查询 {city} 实时天气",
        )
        emit("tool_call", tool="weather", params={"location": city})

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(f"https://wttr.in/{city}", params={"format": "j1"})
                response.raise_for_status()
                data = response.json()
        except Exception as exc:
            logger.warning("Weather lookup failed, fallback to search: %s", exc)
            emit(
                "tool_result",
                tool="weather",
                status="failed",
                result=str(exc),
            )
            return None

        report = self._format_weather_report(question, city, data)
        if not report:
            return None

        emit(
            "tool_result",
            tool="weather",
            status="completed",
            result=report[:500],
        )
        emit(
            "agent_status",
            agent="Weather",
            status="completed",
            detail="实时天气查询完成",
        )

        return {
            "report": report,
            "sources": [
                {
                    "title": "wttr.in weather data",
                    "url": f"https://wttr.in/{city}",
                    "snippet": "实时天气与短期预报数据",
                    "source": "weather",
                }
            ],
            "review_score": 1.0,
            "review_feedback": "Weather route; skipped multi-agent review.",
        }

    @staticmethod
    def _is_weather_question(question: str) -> bool:
        """判断是否为天气、气温、降雨等即时信息问题。"""
        q = question.lower()
        return any(word in q for word in ("天气", "气温", "温度", "下雨", "降雨", "冷不冷", "热不热", "weather"))

    @staticmethod
    def _extract_weather_city(question: str) -> str:
        """从常见中文天气问法中提取城市名。"""
        city_aliases = {
            "南京": "Nanjing",
            "北京": "Beijing",
            "上海": "Shanghai",
            "广州": "Guangzhou",
            "深圳": "Shenzhen",
            "杭州": "Hangzhou",
            "苏州": "Suzhou",
            "成都": "Chengdu",
            "武汉": "Wuhan",
            "西安": "Xi'an",
            "重庆": "Chongqing",
            "天津": "Tianjin",
        }
        for name, query_name in city_aliases.items():
            if name in question:
                return query_name

        match = re.search(r"今天(.+?)(?:天气|气温|温度|会下雨|下雨)", question)
        if match:
            return match.group(1).strip(" 的怎么样如何?")
        return ""

    @staticmethod
    def _format_weather_report(question: str, city: str, data: Dict[str, Any]) -> str:
        """把 wttr.in 返回的天气 JSON 格式化成中文短答案。"""
        current = (data.get("current_condition") or [{}])[0]
        today = (data.get("weather") or [{}])[0]
        area = (data.get("nearest_area") or [{}])[0]
        area_name = ((area.get("areaName") or [{}])[0]).get("value") or city
        region = ((area.get("region") or [{}])[0]).get("value") or ""

        desc = ((current.get("weatherDesc") or [{}])[0]).get("value") or "暂无描述"
        temp = current.get("temp_C", "")
        feels = current.get("FeelsLikeC", "")
        humidity = current.get("humidity", "")
        wind = current.get("windspeedKmph", "")
        wind_dir = current.get("winddir16Point", "")
        precip = current.get("precipMM", "")
        max_temp = today.get("maxtempC", "")
        min_temp = today.get("mintempC", "")
        uv = today.get("uvIndex") or current.get("uvIndex", "")
        date = today.get("date", "")

        rain_chances = []
        for item in today.get("hourly") or []:
            chance = item.get("chanceofrain")
            if chance not in (None, ""):
                try:
                    rain_chances.append(int(chance))
                except ValueError:
                    pass
        max_rain = max(rain_chances) if rain_chances else None

        lines = [
            "## 直接答案",
            "",
            f"今天 {area_name}{f'（{region}）' if region else ''}天气：{desc}。",
        ]
        if temp:
            lines.append(f"当前气温约 {temp}℃，体感约 {feels or temp}℃。")
        if max_temp or min_temp:
            lines.append(f"今日气温大约 {min_temp or '?'}℃ - {max_temp or '?'}℃。")
        if humidity:
            lines.append(f"湿度约 {humidity}%。")
        if wind:
            lines.append(f"风速约 {wind} km/h，风向 {wind_dir or '暂无'}。")
        if precip:
            lines.append(f"当前降水量约 {precip} mm。")
        if max_rain is not None:
            lines.append(f"今日分时预报中的最高降雨概率约 {max_rain}%。")
        if uv:
            lines.append(f"紫外线指数约 {uv}。")

        lines.extend([
            "",
            "## 建议",
            "",
            "- 出门前可以再看一次本地天气 App，实时降雨和雷达图会更准。",
            "- 如果长时间在户外，注意防晒和补水。",
            "",
            "## 来源",
            "",
            f"- wttr.in 实时天气接口（查询城市：{city}，日期：{date or 'today'}）",
            "",
            f"> 原始问题：{question}",
        ])
        return "\n".join(lines)
