"""QueryRouter：在直接搜索和多 Agent 研究之间做轻量路由。"""

import re
from dataclasses import dataclass, field
from typing import Literal

from app.config import settings


RouteName = Literal["direct_search", "multi_agent"]


DEFAULT_MULTI_AGENT_KEYWORDS = (
    "调研",
    "调查",
    "研究",
    "研报",
    "趋势",
    "发展",
    "现状",
    "前景",
    "格局",
    "行业",
    "市场",
    "竞品",
    "对比",
    "比较",
    "分析",
    "深度",
    "报告",
    "方案",
    "规划",
    "可行性",
    "战略",
    "策略",
    "风险",
    "机会",
    "案例",
    "综述",
    "文献",
    "论文",
    "技术选型",
    "架构设计",
    "路线图",
    "生态",
    "预测",
    "洞察",
    "评估",
    "research",
    "survey",
    "trend",
    "market analysis",
    "industry analysis",
    "competitive analysis",
    "feasibility",
    "roadmap",
    "literature review",
)


@dataclass(frozen=True)
class QueryRoute:
    """一次问题路由判断的结果。"""

    route: RouteName
    reason: str
    matched_keywords: list[str] = field(default_factory=list)
    score: int = 0

    @property
    def requires_multi_agent(self) -> bool:
        """是否需要进入多 Agent 工作流。"""
        return self.route == "multi_agent"


class QueryRouter:
    """根据问题关键词和复杂度选择执行路线。

    这里故意使用可解释的规则，而不是再调用一次 LLM 分类：
    用户输入命中“调研/研究/趋势/发展”等复杂任务词时走多 Agent；
    未命中时默认走直接联网搜索，降低简单问答的等待时间。
    """

    def __init__(self) -> None:
        configured = getattr(settings, "MULTI_AGENT_ROUTE_KEYWORDS", "").strip()
        if configured:
            self._keywords = tuple(k.strip() for k in configured.split(",") if k.strip())
        else:
            self._keywords = DEFAULT_MULTI_AGENT_KEYWORDS

    def route(self, query: str) -> QueryRoute:
        """返回问题应走的执行路线。"""
        text = (query or "").strip()
        lowered = text.lower()

        matched = [
            keyword
            for keyword in self._keywords
            if keyword and self._keyword_matches(keyword, text, lowered)
        ]
        if matched:
            return QueryRoute(
                route="multi_agent",
                reason=f"命中多 Agent 关键词：{', '.join(matched[:5])}",
                matched_keywords=matched,
                score=max(2, len(matched) * 2),
            )

        if self._looks_like_compound_task(text):
            return QueryRoute(
                route="multi_agent",
                reason="问题较长且包含多项要求，适合拆解后协作处理",
                score=1,
            )

        return QueryRoute(
            route="direct_search",
            reason="未命中复杂研究关键词，按简单问题直接联网搜索回答",
            score=0,
        )

    def _keyword_matches(self, keyword: str, text: str, lowered: str) -> bool:
        """匹配关键词，并减少项目名或实体名造成的误判。"""
        keyword_lower = keyword.lower()

        if keyword.isascii():
            pattern = rf"(?<![a-z0-9]){re.escape(keyword_lower)}(?![a-z0-9])"
            return re.search(pattern, lowered) is not None

        # “研究生/研究院/研究所”更像实体词，不一定代表要做研究任务。
        if keyword == "研究":
            entity_words = ("研究生", "研究院", "研究所")
            if any(entity in text for entity in entity_words) and text.count("研究") == 1:
                return False

        return keyword in text

    def _looks_like_compound_task(self, text: str) -> bool:
        """识别没有明显关键词、但包含多项要求的长问题。"""
        min_length = getattr(settings, "MULTI_AGENT_ROUTE_MIN_LENGTH", 180)
        if len(text) < min_length:
            return False

        separators = ("，", ",", "；", ";", "\n", "、", "并且", "同时", "以及")
        separator_hits = sum(1 for sep in separators if sep in text)
        compound_markers = ("分别", "全面", "详细", "系统", "深入", "输出", "生成", "撰写")
        marker_hits = sum(1 for marker in compound_markers if marker in text)

        return separator_hits >= 2 or marker_hits >= 1
