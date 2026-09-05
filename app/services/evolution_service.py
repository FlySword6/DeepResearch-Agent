"""Self-evolution service: post-task reflection, skill draft proposals, and confirmation flow."""

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional

from app.models.database import (
    EvolutionDraftModel,
    EvolutionDraftRepository,
)
from app.utils.llm import LLMConfig, llm_call, resolve_model

logger = logging.getLogger(__name__)

HIGH_SCORE_THRESHOLD = 0.65
LOW_SCORE_THRESHOLD = 0.50
MIN_FEEDBACK_CHARS = 20
ANALYSIS_TIMEOUT = 20.0

VALID_AGENTS = ("planner", "researcher", "writer", "reviewer")

ANALYSIS_SYSTEM_PROMPT = """你是研究系统的自我进化分析师。基于一次已完成的研究任务及其质量评审，
提炼一条可复用的经验，并设计一个"技能"草稿（一段注入到 Agent 系统提示词的指令），帮助未来任务做得更好。

要求：
- 高分任务：总结值得保持的做法（如来源标注规范、结构完整性）。
- 低分任务：总结需要避免的失误（如引用缺失、数据不足、结构松散）。
- 技能名称用英文短横线命名（如 citation-discipline）。
- agents 只能从 planner、researcher、writer、reviewer 中选 1-3 个。
- content 用中文，2-5 句话，可直接作为 Agent 指令。

仅输出有效 JSON：
{
  "lesson": "经验总结（50 字以内）",
  "name": "skill-name",
  "description": "一句话描述",
  "trigger_keywords": ["关键词1", "关键词2"],
  "agents": ["planner"],
  "content": "指令正文"
}"""


def _to_dict(draft: EvolutionDraftModel) -> dict:
    return {
        "id": draft.id,
        "task_id": draft.task_id,
        "profile_id": draft.profile_id,
        "review_score": draft.review_score,
        "review_feedback": draft.review_feedback,
        "lesson": draft.lesson,
        "draft_name": draft.draft_name,
        "draft_description": draft.draft_description,
        "draft_trigger_keywords": json.loads(draft.draft_trigger_keywords or "[]"),
        "draft_agents": json.loads(draft.draft_agents or "[]"),
        "draft_content": draft.draft_content,
        "promote_global": draft.promote_global,
        "status": draft.status,
        "created_at": draft.created_at.isoformat() if draft.created_at else None,
    }


def _should_analyze(score: float, feedback: str) -> bool:
    if score >= HIGH_SCORE_THRESHOLD or score <= LOW_SCORE_THRESHOLD:
        return len((feedback or "").strip()) >= MIN_FEEDBACK_CHARS
    return False


def _should_analyze_with_log(score: float, feedback: str) -> bool:
    """Like _should_analyze but logs why analysis was skipped."""
    if score < HIGH_SCORE_THRESHOLD and score > LOW_SCORE_THRESHOLD:
        logger.info(
            "Evolution skipped: score %.2f in (%.2f, %.2f) band",
            score,
            LOW_SCORE_THRESHOLD,
            HIGH_SCORE_THRESHOLD,
        )
        return False
    if len((feedback or "").strip()) < MIN_FEEDBACK_CHARS:
        logger.info(
            "Evolution skipped: feedback too short (%d chars)",
            len((feedback or "").strip()),
        )
        return False
    return True


def _parse_proposal(response: str) -> Optional[dict]:
    pattern = r"```(?:json)?\s*\n?([\s\S]*?)\n?```"
    match = re.search(pattern, response)
    json_str = match.group(1).strip() if match else response.strip()
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        return None
    name = str(data.get("name", "")).strip()
    content = str(data.get("content", "")).strip()
    agents = [a for a in data.get("agents", []) if a in VALID_AGENTS]
    if not name or not content or not agents:
        return None
    return {
        "lesson": str(data.get("lesson", ""))[:200],
        "name": name[:128],
        "description": str(data.get("description", ""))[:500],
        "trigger_keywords": [str(k) for k in data.get("trigger_keywords", [])][:10],
        "agents": agents[:3],
        "content": content,
    }


async def _propose_skill(
    task_text: str, plan_summary: str, score: float, feedback: str
) -> Optional[dict]:
    user_prompt = (
        f"研究任务：{task_text}\n\n"
        f"研究计划：\n{plan_summary}\n\n"
        f"评审分数：{score}\n\n"
        f"评审反馈：\n{feedback[:3000]}\n\n"
        "请输出一个技能提案 JSON。"
    )
    config = LLMConfig(model=resolve_model(None), temperature=0.4, max_tokens=1024)
    try:
        response = await asyncio.wait_for(
            llm_call(
                system_prompt=ANALYSIS_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                config=config,
            ),
            timeout=ANALYSIS_TIMEOUT,
        )
    except Exception as exc:
        logger.warning("Evolution LLM proposal failed: %s", exc)
        return None
    return _parse_proposal(response)


async def _create_draft(
    task_id: str,
    profile_id: Optional[str],
    score: float,
    feedback: str,
    proposal: dict,
) -> Optional[dict]:
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = EvolutionDraftRepository(session)
        draft = EvolutionDraftModel(
            id=f"draft_{uuid.uuid4().hex[:12]}",
            task_id=task_id,
            profile_id=profile_id or "profile_default",
            review_score=score,
            review_feedback=str(feedback)[:2000],
            lesson=proposal["lesson"],
            draft_name=proposal["name"],
            draft_description=proposal["description"],
            draft_trigger_keywords=json.dumps(proposal["trigger_keywords"], ensure_ascii=False),
            draft_agents=json.dumps(proposal["agents"], ensure_ascii=False),
            draft_content=proposal["content"],
            promote_global=False,
            status="pending",
        )
        created = await repo.create(draft)
    return _to_dict(created)


async def analyze_task(task_id: str, state: Any) -> Optional[dict]:
    """Reflect on a completed task and create a skill draft. Never raises."""
    try:
        score = float(getattr(state, "review_score", 0.0) or 0.0)
        feedback = str(getattr(state, "review_feedback", "") or "")
        profile_id = getattr(state, "profile_id", None)
        if not _should_analyze_with_log(score, feedback):
            return None
        from app.models.database import _async_session_maker

        async with _async_session_maker() as session:
            repo = EvolutionDraftRepository(session)
            if await repo.get_by_task(task_id) is not None:
                return None
        task_text = str(getattr(state, "task", "") or "")
        plan_lines = []
        for subtask in getattr(state, "plan", []) or []:
            plan_lines.append(f"- {getattr(subtask, 'description', subtask)}")
        plan_summary = "\n".join(plan_lines)[:2000] or "(无计划)"
        proposal = await _propose_skill(task_text, plan_summary, score, feedback)
        if proposal is None:
            return None
        return await _create_draft(task_id, profile_id, score, feedback, proposal)
    except Exception as exc:
        logger.warning("Evolution analysis skipped for task %s: %s", task_id, exc)
        return None


async def list_drafts(profile_id: str, status: str = "pending") -> List[dict]:
    """Return drafts for a profile, newest first."""
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = EvolutionDraftRepository(session)
        drafts = await repo.list_for_profile(profile_id, status=status)
        return [_to_dict(d) for d in drafts]


async def accept_draft(
    draft_id: str,
    profile_id: str,
    promote_global: bool = False,
    edits: Optional[Dict[str, Any]] = None,
) -> Optional[dict]:
    """Accept a draft, creating a real skill. Returns the created skill or None."""
    from app.models.database import _async_session_maker
    from app.services.skill_service import create_skill

    async with _async_session_maker() as session:
        repo = EvolutionDraftRepository(session)
        draft = await repo.get(draft_id)
        if draft is None or draft.profile_id != profile_id:
            return None
        draft_data = _to_dict(draft)

    edits = edits or {}
    skill = await create_skill({
        "name": edits.get("name", draft_data["draft_name"]),
        "description": edits.get("description", draft_data["draft_description"]),
        "trigger_keywords": edits.get(
            "trigger_keywords", draft_data["draft_trigger_keywords"]
        ),
        "agents": edits.get("agents", draft_data["draft_agents"]),
        "content": edits.get("content", draft_data["draft_content"]),
        "owner_id": None if promote_global else profile_id,
    })

    async with _async_session_maker() as session:
        repo = EvolutionDraftRepository(session)
        draft = await repo.get(draft_id)
        draft.status = "accepted"
        draft.promote_global = promote_global
        await repo.update(draft)
    return skill


async def reject_draft(draft_id: str, profile_id: str) -> bool:
    """Reject a draft. Returns False if not found or not owned."""
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = EvolutionDraftRepository(session)
        draft = await repo.get(draft_id)
        if draft is None or draft.profile_id != profile_id:
            return False
        draft.status = "rejected"
        await repo.update(draft)
    return True
