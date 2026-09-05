"""WriterAgent - synthesizes research findings into a structured, cited report."""

import json
import logging
import re
from datetime import datetime

from app.agents.base import BaseAgent
from app.utils.llm import LLMConfig, llm_call, resolve_model

logger = logging.getLogger(__name__)

_MIN_REPORT_CHARS = 2000


class WriterAgent(BaseAgent):
    def __init__(self, model_name=None, temperature=0.3, max_tokens=8192):
        super().__init__(model_name, temperature, max_tokens)

    def system_prompt(self):
        from app.utils.date_hint import today_hint

        return f"""{today_hint()}

你是一名专业的研究报告撰写专家。请用中文撰写全面、深入的研究报告。

## 报告结构要求

# 标题

## 摘要
简要的执行摘要（200-300字）。

## 1. 研究背景
背景和目的。

## 2. 核心发现
列出 3-5 个关键研究发现，每个发现都必须注明信息来源。
引用格式：[来源: 网站/页面标题](URL)

## 3. 关键数据与证据
展示从研究数据中获取的具体数据点、统计数字和证据。
如果缺少定量数据，请基于已有信息进行定性分析。

## 4. 详细分析
按主题组织的深度分析（至少 3 个方面）。引用具体的数据点和来源。

## 5. 评估与展望
基于发现的评估和未来趋势。

## 6. 结论与建议
可操作的结论（3-5 条）。

## 参考来源
列出报告中使用的所有数据来源，使用编号列表。

## 写作规范
- 报告正文不少于 2000 字
- 每个关键事实、数据点、引用必须注明来源
- 使用「[来源: 名称](URL)」格式
- 如果数据不足，请明确说明，并基于已有信息合理分析
- 保持客观、专业的学术风格"""

    async def invoke(self, state, tools=None):
        try:
            from app.services.skill_service import enrich_prompt

            context = self._format_research_context(state)
            source_list = self._format_source_list(state)

            user_prompt = (
                f"研究任务: {state.task}\n\n"
                f"研究计划:\n{self._format_plan(state)}\n\n"
                f"研究数据:\n{context}\n\n"
                f"可用来源列表:\n{source_list}\n\n"
                "请基于以上数据撰写一份全面的研究报告。\n"
                "要求：\n"
                "1. 报告正文不少于 2000 字\n"
                "2. 每个事实都必须注明来源，格式为 [来源: 标题](URL)\n"
                "3. 报告末尾必须列出「参考来源」章节\n"
                "4. 如果数据不足，明确说明并给出合理的分析"
            )

            perspectives = getattr(state, "perspectives", []) or []
            if perspectives:
                user_prompt = (
                    "研究视角：\n"
                    + "\n".join(f"- {p}" for p in perspectives)
                    + "\n\n"
                    + user_prompt
                )

            workspace_dir = getattr(state, "workspace_dir", "")
            if workspace_dir:
                user_prompt += (
                    f"\n\n【输出要求】\n"
                    f"报告将保存到工作目录 {workspace_dir}。"
                    f"如报告需要引用参考文件，请使用该目录下的文件名。"
                )

            model = resolve_model(self.model_name)
            config = LLMConfig(model=model, temperature=0.3, max_tokens=self.max_tokens)
            plan_extra = "\n".join(
                f"- {getattr(st, 'description', st)}"
                for st in getattr(state, "plan", []) or []
            )[:1500]
            enriched_prompt = await enrich_prompt(
                self.system_prompt(),
                "writer",
                state.task,
                getattr(state, "profile_id", None),
                extra_context=plan_extra,
            )
            report = await llm_call(
                system_prompt=enriched_prompt,
                user_prompt=user_prompt,
                config=config,
            )
            report = report.strip()

            # Enforce minimum length; if LLM returned short, pad with fallback
            if len(report) < _MIN_REPORT_CHARS:
                logger.warning(
                    "WriterAgent report too short (%d chars), appending fallback sections",
                    len(report),
                )
                report = self._extend_report(report, state)

            return {"report_draft": report}

        except Exception as e:
            logger.warning(f"WriterAgent LLM call failed: {e}")
            return {"report_draft": self._fallback_report(state)}

    def _format_plan(self, state):
        lines = []
        for i, task in enumerate(state.plan):
            lines.append(f"  {i+1}. [{task.tool}] {task.description}")
        return "\n".join(lines)

    def _format_research_context(self, state):
        """Format research data with source URLs attached, within a budget."""
        from app.config import settings
        from app.utils.context import truncate_research_context

        sections = []
        for i, item in enumerate(
            truncate_research_context(state.research_data, settings.CONTEXT_MAX_CHARS)
        ):
            desc = item.get("description", "")
            tool = item.get("tool", "")
            summary = item.get("summary", item.get("result", ""))
            cleaned = self._clean_raw_output(str(summary))
            if cleaned and len(cleaned) > 10:
                sections.append(f"### {desc}（工具: {tool}）\n{cleaned}\n")
        return "\n\n".join(sections) if sections else "No data."

    def _format_source_list(self, state) -> str:
        """Format the collected sources into a markdown list for the writer prompt."""
        seen = set()
        entries = []
        for s in state.sources:
            url = s.get("url", "")
            title = s.get("title", "")
            if url and url not in seen:
                seen.add(url)
                entries.append(f"- [{title}]({url})")
        if not entries:
            # Fall back to extracting URLs from research_data
            for item in state.research_data:
                raw = str(item.get("raw_result", "") or item.get("summary", ""))
                for m in re.finditer(r"https?://[^\s)\]]+", raw):
                    url = m.group(0).rstrip(".,;")
                    if url not in seen:
                        seen.add(url)
                        entries.append(f"- [{url}]({url})")
        return "\n".join(entries) if entries else "(无可用来源)"

    def _extend_report(self, report: str, state) -> str:
        """If the LLM report is too short, append structured fallback sections."""
        lines = [report, "\n\n---\n"]

        # Collect remaining research data items not already covered
        for i, item in enumerate(state.research_data):
            desc = item.get("description", "")
            summary = str(item.get("summary", item.get("result", "")))
            cleaned = self._clean_raw_output(summary)
            if cleaned and len(cleaned) > 10:
                lines.append(f"\n### 补充数据: {desc}\n")
                lines.append(cleaned + "\n")

        return "\n".join(lines)

    def _fallback_report(self, state):
        lines = []
        lines.append(f"# {state.task}")
        lines.append("")
        lines.append(f"> **生成时间**：{datetime.now().strftime('%Y年%m月%d日')}")
        lines.append("")

        # Collect sources for the references section
        source_urls = set()
        for s in state.sources:
            u = s.get("url", "")
            if u:
                source_urls.add(u)

        lines.append("## 摘要")
        lines.append("")
        subtask_count = len(state.research_data)
        source_count = len(source_urls)
        lines.append(
            f"本报告围绕「{state.task}」进行了系统性研究，"
            f"完成了 {subtask_count} 个研究步骤，"
            f"参考了 {source_count} 个信息来源。以下为主要发现。"
        )

        for i, item in enumerate(state.research_data):
            desc = item.get("description", "")
            raw = str(item.get("summary", item.get("result", item.get("raw_result", ""))))
            cleaned = self._clean_raw_output(raw)
            if cleaned and len(cleaned) > 10:
                lines.append("")
                lines.append(f"### {desc}")
                lines.append("")
                lines.append(cleaned)

        if source_urls:
            lines.append("")
            lines.append("## 参考来源")
            lines.append("")
            for i, url in enumerate(sorted(source_urls), 1):
                lines.append(f"{i}. {url}")

        lines.append("")
        lines.append("---")
        lines.append(f"*报告由 DeepResearch-Agent 自动生成 · {datetime.now().strftime('%Y-%m-%d')}*")
        return "\n".join(lines)

    @staticmethod
    def _clean_raw_output(raw):
        """Format tool output into readable text regardless of tool type."""
        if not raw:
            return ""

        if isinstance(raw, dict):
            if "stdout" in raw:
                out = raw.get("stdout", "").strip()
                err = raw.get("stderr", "").strip()
                if out and err:
                    return f"{out}\n\n{err}"
                return out or err or "(no output)"
            if "content" in raw and "url" in raw:
                content = str(raw.get("content", ""))[:1000]
                url = raw.get("url", "")
                return f"来源: [{raw.get('title', url)}]({url})\n\n{content}"
            parts = []
            for k, v in raw.items():
                if v and k not in ("execution_time",):
                    parts.append(f"{k}: {str(v)[:300]}")
            return "\n".join(parts) if parts else str(raw)

        text = str(raw).strip()
        if not text:
            return ""

        # JSON array of search results
        if text.startswith("["):
            try:
                items = json.loads(text)
                if isinstance(items, list) and items:
                    out = []
                    for item in items[:5]:
                        t = item.get("title", "").strip()
                        s = (item.get("snippet") or item.get("content") or "").strip().replace("\\n", "\n")[:500]
                        u = item.get("url", "")
                        if t:
                            out.append(f"**{t}**")
                        if u:
                            out.append(f"链接: [{u}]({u})")
                        if s:
                            out.append(s)
                        out.append("")
                    return "\n".join(out)
            except json.JSONDecodeError:
                pass

        text = re.sub(r"\s+", " ", text).strip()
        return text[:1000] if text else ""
