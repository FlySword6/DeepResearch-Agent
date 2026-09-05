"""PlannerAgent - Task decomposition expert."""

import json
import logging
import re
from typing import Any, Dict

from app.agents.base import BaseAgent
from app.models.state import ResearchState, SubTask
from app.utils.llm import LLMConfig, llm_call, resolve_model

logger = logging.getLogger(__name__)


class PlannerAgent(BaseAgent):
    def __init__(self, model_name=None, temperature=0.5, max_tokens=4096, use_rag=False):
        super().__init__(model_name, temperature, max_tokens)
        self.use_rag = use_rag

    def system_prompt(self):
        from app.utils.date_hint import today_hint
        from app.utils.workspace_context import build_workspace_instruction

        tools_desc = '"search"（网络搜索）、"browse"（深度阅读指定页面）、"analyze"（数据分析和综合）、"read_workspace"（读取工作目录中的参考文件）'
        if self.use_rag:
            tools_desc += '、"rag"（从知识库检索）'

        env = build_workspace_instruction(
            getattr(self, "workspace_dir", ""),
            getattr(self, "workspace_files", []),
        )

        return f"""{today_hint()}

{env}

你是一名研究规划专家。请将复杂的研究任务拆解为 5-8 个具体、可执行的子任务。

每个子任务必须包含：
- id: 短横线命名法的标识符（例如 "background-research"）
- description: 清晰、可操作的**具体研究角度**（不要笼统的 "研究 X 的背景"，而要写 "搜索 X 在 2025-2026 年的最新发展动态"）
- tool: 以下工具之一——{tools_desc}

子任务设计原则：
1. **多样化角度**：从不同维度切入（技术、市场、对比、趋势、案例分析等）
2. **由浅入深**：前 2-3 个做背景搜索，中间 2-3 个深入特定角度，最后 1-2 个做综合
3. **工具轮换**：交替使用 search、browse、analyze
4. **browse 任务需要指向明确 URL**（如果已知的话），否则用 search

重要：仅输出有效的 JSON，不要附加任何其他文本。请先给出 3-5 个不同的研究视角（如技术演进、市场生态、风险挑战、案例对比），再为每个视角拆解出具体、可执行的子任务。输出必须是如下 JSON 对象：

{{
  "perspectives": ["视角一：技术演进", "视角二：市场生态", "视角三：风险挑战"],
  "subtasks": [
    {{"id": "background-research", "description": "搜索 X 在 2025-2026 年的最新发展动态和趋势", "tool": "search"}},
    {{"id": "deep-analysis", "description": "深入分析 Y 的核心技术原理和应用场景", "tool": "search"}},
    {{"id": "synthesis", "description": "综合以上研究结果，总结关键发现和结论", "tool": "analyze"}}
  ]
}}

描述要可操作、具体，并且与原始研究主题紧密相关。"""

    async def invoke(self, state, tools=None):
        try:
            from app.services.skill_service import enrich_prompt

            self.workspace_dir = getattr(state, "workspace_dir", "")
            self.workspace_files = list(getattr(state, "workspace_files", []) or [])

            config = LLMConfig(
                model=resolve_model(self.model_name),
                temperature=self.temperature,
                max_tokens=self.max_tokens,
            )
            user_prompt = f"Research Task: {state.task}\n\nDecompose this into 5-8 focused subtasks with diverse angles and tools."
            enriched_prompt = await enrich_prompt(
                self.system_prompt(),
                "planner",
                state.task,
                getattr(state, "profile_id", None),
            )
            response = await llm_call(
                system_prompt=enriched_prompt,
                user_prompt=user_prompt,
                config=config,
            )
            parsed = self._parse_plan(response)
            subtasks = parsed.get("subtasks") or []
            if subtasks and len(subtasks) >= 4:
                plan = []
                for i, st in enumerate(subtasks[:10]):
                    plan.append(SubTask(
                        id=st.get("id", f"step-{i+1}"),
                        description=st.get("description", ""),
                        tool=st.get("tool", "search"),
                        status="pending",
                    ))
                return {
                    "plan": plan,
                    "perspectives": parsed.get("perspectives", []),
                }
        except Exception as e:
            logger.warning(f"PlannerAgent LLM call failed: {e}")

        return self._fallback_plan(state)

    def _parse_plan(self, response: str) -> Dict[str, Any]:
        """Parse perspectives + subtasks JSON; accepts a bare list for compat."""
        pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
        match = re.search(pattern, response)
        json_str = match.group(1).strip() if match else response.strip()
        try:
            parsed = json.loads(json_str)
        except json.JSONDecodeError:
            return {"subtasks": [], "perspectives": []}
        if isinstance(parsed, list):
            return {"subtasks": parsed, "perspectives": []}
        if isinstance(parsed, dict):
            subtasks = parsed.get("subtasks", parsed.get("plan", None))
            if isinstance(subtasks, list):
                return {
                    "subtasks": subtasks,
                    "perspectives": parsed.get("perspectives", []),
                }
            for v in parsed.values():
                if isinstance(v, list):
                    return {
                        "subtasks": v,
                        "perspectives": parsed.get("perspectives", []),
                    }
        return {"subtasks": [], "perspectives": []}

    def _fallback_plan(self, state: ResearchState) -> Dict[str, Any]:
        task = state.task
        plan = [
            SubTask(id="background", description=f"搜索 {task} 的背景信息和最新动态", tool="search", status="pending"),
            SubTask(id="deep-dive-1", description=f"深入分析 {task} 的核心技术、关键特征", tool="search", status="pending"),
            SubTask(id="deep-dive-2", description=f"搜索 {task} 的应用场景、优势和局限性", tool="search", status="pending"),
        ]
        if self.use_rag:
            plan.append(SubTask(id="knowledge", description=f"从知识库检索关于 {task} 的已有知识", tool="rag", status="pending"))
        plan.append(SubTask(id="comparison", description=f"对比分析 {task} 与其他相关方案的异同", tool="search", status="pending"))
        plan.append(SubTask(id="synthesis", description=f"综合所有研究发现，总结 {task} 的核心结论和趋势", tool="analyze", status="pending"))
        return {"plan": plan}
