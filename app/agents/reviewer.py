"""ReviewerAgent - quality assurance for research reports with actionable Chinese feedback."""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

from app.agents.base import BaseAgent
from app.models.state import ResearchState
from app.utils.llm import LLMConfig, llm_call, resolve_model

logger = logging.getLogger(__name__)

# Lower threshold to account for realistic LLM scoring variance
# The agent will iterate when score < threshold, which drives improvement
_PASSING_THRESHOLD = 0.5


class ReviewerAgent(BaseAgent):
    """
    ReviewerAgent evaluates research report quality on multiple dimensions
    and produces a score with actionable Chinese-language feedback.
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.3,
        max_tokens: int = 2048,
    ):
        super().__init__(model_name, temperature, max_tokens)

    PERSONAS = [
        ("怀疑派实践者", "重点核查论断是否有证据支撑、引用是否真实可达、是否过度概括。"),
        ("对抗性评审", "重点核查是否遗漏反方观点、数据是否被选择性使用、结论是否超出证据范围。"),
        ("实现工程师", "重点核查报告是否可落地、建议是否可操作、术语与数字是否准确。"),
    ]

    def system_prompt(self) -> str:
        from app.utils.date_hint import today_hint

        return (
            f"{today_hint()}\n\n"
            """你是一名研究报告质量评审专家。请从以下四个维度评估报告质量，每项满分 10 分：

1. **信息完整性**（权重 30%）：是否覆盖了研究问题的所有核心方面？是否有明显的信息缺口？
2. **引用质量**（权重 25%）：是否每个关键事实都有明确来源？引用格式是否规范？
3. **逻辑连贯性**（权重 25%）：结构是否清晰？论证是否合理？是否容易理解？
4. **分析深度**（权重 20%）：是否提供了超越表面信息的真知灼见？是否有数据支撑？

输出格式：仅输出有效的 JSON，不要附加任何其他文本。

{
  "score": 0.0-1.0,
  "feedback": "你的中文反馈，包括：1) 各维度评分和理由 2) 具体改进建议 3) 缺失哪些重要内容",
  "passed": true/false
}

评分标准：
- 0.7+：良好，达到要求
- 0.5-0.7：及格，需要改进
- 0.5 以下：不及格，需要大幅修改

低分时，feedback 必须包含具体的改进方向。"""
        )

    async def invoke(
        self,
        state: ResearchState,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Evaluate the report with three critic personas; score = strictest."""
        if not state.report_draft:
            return {
                "review_score": 0.0,
                "review_feedback": "没有报告草稿可供评估。",
                "iteration_count": state.iteration_count + 1,
            }

        try:
            from app.services.skill_service import enrich_prompt

            plan_str = self._format_plan(state)
            config = LLMConfig(
                model=resolve_model(self.model_name),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            base_system = await enrich_prompt(
                self.system_prompt(),
                "reviewer",
                state.task,
                getattr(state, "profile_id", None),
                extra_context=plan_str,
            )
            results = await asyncio.gather(
                *(
                    self._review_persona(name, instruction, base_system, state, plan_str, config)
                    for name, instruction in self.PERSONAS
                )
            )
            scores = [s for _, s, _ in results]
            merged_feedback = " | ".join(f"[{name}] {fb}" for name, _, fb in results)
            return {
                "review_score": min(scores),
                "review_feedback": merged_feedback,
                "iteration_count": state.iteration_count + 1,
            }

        except Exception as e:
            logger.warning(f"ReviewerAgent LLM call failed, using heuristic: {e}")
            return self._heuristic_review(state)

    async def _review_persona(
        self,
        name: str,
        instruction: str,
        base_system: str,
        state: ResearchState,
        plan_str: str,
        config: LLMConfig,
    ):
        """Run one critic persona and return (name, score, feedback)."""
        system = (
            f"{base_system}\n\n当前角色：{name}。{instruction}\n\n"
            "仅输出 JSON：{\"score\": 0.0-1.0, \"feedback\": \"...\"}"
        )
        user = (
            f"原始研究任务: {state.task}\n\n研究计划:\n{plan_str}\n\n"
            f"报告草稿:\n{state.report_draft}\n\n请按你的角色评审并给出 0.0-1.0 的分数。"
        )
        response = await llm_call(system_prompt=system, user_prompt=user, config=config)
        parsed = self._parse_review(response)
        return name, parsed.get("score", 0.0), parsed.get("feedback", "评审完成。")

    def _parse_review(self, response: str) -> Dict[str, Any]:
        """Parse JSON review from LLM response."""
        pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
        match = re.search(pattern, response)

        json_str = match.group(1).strip() if match else response.strip()

        try:
            parsed = json.loads(json_str)
            return {
                "score": float(parsed.get("score", 0.0)),
                "feedback": str(parsed.get("feedback", "")),
                "passed": bool(parsed.get("passed", False)),
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            return {"score": 0.0, "feedback": "无法解析评审结果。", "passed": False}

    def _heuristic_review(self, state: ResearchState) -> Dict[str, Any]:
        """Score report based on heuristics when LLM is unavailable."""
        score = 0.0
        feedback_parts = []
        report = state.report_draft

        # Length-based heuristic
        char_count = len(report)
        if char_count > 1500:
            score += 0.25
            feedback_parts.append(f"报告篇幅充足（{char_count} 字）。")
        elif char_count > 800:
            score += 0.15
            feedback_parts.append(f"报告篇幅适中（{char_count} 字），建议再充实一些。")
        else:
            feedback_parts.append(f"报告篇幅过短（{char_count} 字），需要大幅扩充。")

        # Section coverage heuristic
        required_sections = [
            "摘要", "背景", "发现", "分析",
            "结论", "参考来源", "来源",
        ]
        report_lower = report.lower()
        sections_found = sum(1 for s in required_sections if s.lower() in report_lower)
        section_score = min(0.35, sections_found * 0.05)
        score += section_score
        feedback_parts.append(f"覆盖了 {sections_found}/{len(required_sections)} 个必要章节。")

        # Citation quality heuristic
        citation_patterns = [
            r"\[来源:",
            r"\[.*?\]\(https?://",
            r"来源:",
            r"http[s]?://[^\s)\]]+",
        ]
        citation_count = sum(1 for pat in citation_patterns if re.search(pat, report))
        if citation_count >= 2:
            score += 0.25
            feedback_parts.append("有规范的引用格式。")
        elif citation_count >= 1:
            score += 0.15
            feedback_parts.append("引用较少，建议增加来源标注。")
        else:
            feedback_parts.append("缺少引用来源标注。")

        # Data presence heuristic
        has_numbers = any(c.isdigit() for c in report)
        if has_numbers:
            score += 0.15
            feedback_parts.append("包含具体数据点。")

        score = min(1.0, max(0.0, score))
        feedback = " | ".join(feedback_parts)

        return {
            "review_score": score,
            "review_feedback": feedback,
            "iteration_count": state.iteration_count + 1,
        }

    @staticmethod
    def _format_plan(state: ResearchState) -> str:
        """Format the research plan as a string."""
        lines = []
        for i, task in enumerate(state.plan[:10]):
            lines.append(f"  {i+1}. [{task.tool}] {task.description}")
        return "\n".join(lines)
