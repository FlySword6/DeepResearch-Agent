"""Skill service: CRUD, trigger matching, and prompt enrichment for user-defined skills."""

import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from app.models.database import SkillModel, SkillRepository

logger = logging.getLogger(__name__)

VALID_AGENTS = ("planner", "researcher", "writer", "reviewer")

BUILTIN_SKILLS: List[Dict[str, Any]] = [
    {
        "name": "executive-summary",
        "description": "报告面向管理层读者时，结论先行并给出执行摘要",
        "trigger_keywords": ["报告", "总结", "决策", "管理层", "executive"],
        "agents": ["writer"],
        "content": (
            "当报告面向需要快速决策的管理层读者时，在正文开头增加\"执行摘要\"部分："
            "用不超过 5 句话概括核心结论、关键数据与行动建议，结论先行，避免铺垫。"
        ),
    },
    {
        "name": "code-review-analysis",
        "description": "任务涉及代码、软件架构或技术方案时，增加代码审查研究维度",
        "trigger_keywords": ["代码", "软件", "架构", "技术方案", "实现", "框架", "langchain", "langgraph"],
        "agents": ["planner", "researcher"],
        "content": (
            "当研究任务涉及代码、软件架构或技术方案时，额外覆盖以下维度："
            "代码可维护性与可读性、测试覆盖、安全性风险、性能瓶颈、与现有技术栈的兼容性。"
        ),
    },
    {
        "name": "market-comparison",
        "description": "报告涉及市场、竞品或方案对比时，使用对比矩阵组织内容",
        "trigger_keywords": ["市场", "竞品", "对比", "比较", "差异", "方案选择", "选型", "哪个好"],
        "agents": ["planner", "writer"],
        "content": (
            "当报告涉及市场、竞品或方案对比时，使用对比矩阵组织内容："
            "维度（功能、价格、性能、生态、风险）为行，对比对象为列，"
            "并为每个维度给出关键数据与来源。"
        ),
    },
]


class DuplicateSkillNameError(Exception):
    """Raised when creating/updating a skill with a duplicate name."""


class InvalidSkillError(Exception):
    """Raised when skill payload fails validation."""


# In-memory cache of serialized skills; invalidated on any CRUD change.
_skills_cache: Optional[List[dict]] = None


def invalidate_cache() -> None:
    global _skills_cache
    _skills_cache = None


def _to_dict(skill: SkillModel) -> dict:
    return {
        "id": skill.id,
        "owner_id": skill.owner_id,
        "name": skill.name,
        "description": skill.description,
        "trigger_keywords": json.loads(skill.trigger_keywords or "[]"),
        "agents": json.loads(skill.agents or "[]"),
        "content": skill.content,
        "enabled": skill.enabled,
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
        "updated_at": skill.updated_at.isoformat() if skill.updated_at else None,
    }


def _validate_agents(agents: List[str]) -> None:
    for agent in agents:
        if agent not in VALID_AGENTS:
            raise InvalidSkillError(f"无效的 Agent: {agent}")


async def _load_all() -> List[dict]:
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = SkillRepository(session)
        return [_to_dict(skill) for skill in await repo.list_all()]


async def list_skills() -> List[dict]:
    """Return all skills (cached)."""
    global _skills_cache
    if _skills_cache is None:
        try:
            _skills_cache = await _load_all()
        except Exception as exc:
            logger.warning("Failed to load skills: %s", exc)
            _skills_cache = []
    return list(_skills_cache)


async def _profile_skill_ids(profile_id: str) -> List[str]:
    """IDs of skills visible to a profile: private + globals not explicitly disabled."""
    from app.models.database import UserSkillPrefRepository, _async_session_maker

    async with _async_session_maker() as session:
        repo = SkillRepository(session)
        prefs = UserSkillPrefRepository(session)
        disabled = await prefs.list_disabled(profile_id)
        skills = await repo.list_for_profile(profile_id, disabled)
        return [s.id for s in skills]


async def list_skills_for_profile(profile_id: Optional[str] = None) -> List[dict]:
    """All skills with owner_id and enabled_for_me flags for a profile."""
    if profile_id is None:
        from app.services.profile_service import get_default_profile

        profile_id = (await get_default_profile())["id"]
    visible = set(await _profile_skill_ids(profile_id))
    result = []
    for skill in await list_skills():
        if skill["owner_id"] is not None and skill["owner_id"] != profile_id:
            continue  # other profiles' private skills are invisible
        item = dict(skill)
        item["enabled_for_me"] = item["owner_id"] == profile_id or (
            item["owner_id"] is None and item["id"] in visible
        )
        result.append(item)
    return result


async def get_skill(skill_id: str) -> Optional[dict]:
    """Return one skill by id, or None."""
    for skill in await list_skills():
        if skill["id"] == skill_id:
            return skill
    return None


async def create_skill(data: Dict[str, Any]) -> dict:
    """Create a skill and return it as a dict. Raises on duplicate name or invalid agents."""
    global _skills_cache
    from app.models.database import _async_session_maker

    agents = data.get("agents", [])
    _validate_agents(agents)
    async with _async_session_maker() as session:
        repo = SkillRepository(session)
        if await repo.get_by_name(data["name"]):
            raise DuplicateSkillNameError(f"技能名称已存在: {data['name']}")
        skill = SkillModel(
            id=f"skill_{uuid.uuid4().hex[:12]}",
            name=data["name"],
            description=data.get("description", ""),
            trigger_keywords=json.dumps(data.get("trigger_keywords", []), ensure_ascii=False),
            agents=json.dumps(agents, ensure_ascii=False),
            content=data["content"],
            enabled=data.get("enabled", True),
            owner_id=data.get("owner_id"),
        )
        created = await repo.create(skill)
    _skills_cache = None
    return _to_dict(created)


async def update_skill(skill_id: str, data: Dict[str, Any]) -> Optional[dict]:
    """Update a skill. Returns updated dict, or None if the skill does not exist."""
    global _skills_cache
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = SkillRepository(session)
        skill = await repo.get(skill_id)
        if skill is None:
            return None
        if "name" in data and data["name"] != skill.name:
            if await repo.get_by_name(data["name"]):
                raise DuplicateSkillNameError(f"技能名称已存在: {data['name']}")
            skill.name = data["name"]
        if "description" in data:
            skill.description = data["description"]
        if "trigger_keywords" in data:
            skill.trigger_keywords = json.dumps(data["trigger_keywords"], ensure_ascii=False)
        if "agents" in data:
            _validate_agents(data["agents"])
            skill.agents = json.dumps(data["agents"], ensure_ascii=False)
        if "content" in data:
            skill.content = data["content"]
        if "enabled" in data:
            skill.enabled = data["enabled"]
        updated = await repo.update(skill)
        await session.refresh(updated)
    _skills_cache = None
    return _to_dict(updated)


async def delete_skill(skill_id: str) -> bool:
    """Delete a skill. Returns True if deleted, False if not found."""
    global _skills_cache
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = SkillRepository(session)
        deleted = await repo.delete(skill_id)
    if deleted:
        _skills_cache = None
    return deleted


def _matches(skill: dict, text: str) -> bool:
    """Keyword match against task + extra context (plan/subtasks/research).

    - No keywords  -> always matches (skill applies to every task).
    - Exact substring match, case-insensitive.
    - For space-separated English keywords, any single token also matches.
    """
    keywords = skill["trigger_keywords"]
    if not keywords:
        return True
    lowered = text.lower()
    for k in keywords:
        kw = str(k).lower().strip()
        if not kw:
            continue
        if kw in lowered:
            return True
        tokens = [tok for tok in kw.split() if len(tok) >= 3]
        if tokens and any(tok in lowered for tok in tokens):
            return True
    return False


async def match_skills(
    task_text: str,
    agent_name: str,
    profile_id: Optional[str] = None,
    extra_context: str = "",
) -> List[dict]:
    """Return enabled skills visible to a profile whose agent scope and keywords match."""
    if profile_id is None:
        from app.services.profile_service import get_default_profile

        profile_id = (await get_default_profile())["id"]
    visible = set(await _profile_skill_ids(profile_id))
    skills = await list_skills()
    combined = f"{task_text or ''}\n{extra_context or ''}"
    return [
        s
        for s in skills
        if s["id"] in visible
        and s["enabled"]
        and agent_name in s["agents"]
        and _matches(s, combined)
    ]


async def set_skill_pref(profile_id: str, skill_id: str, enabled: bool) -> bool:
    """Enable/disable a global skill for a profile. Returns False if skill is not global."""
    from app.models.database import UserSkillPrefRepository, _async_session_maker

    async with _async_session_maker() as session:
        repo = SkillRepository(session)
        skill = await repo.get(skill_id)
        if skill is None or skill.owner_id is not None:
            return False
        prefs = UserSkillPrefRepository(session)
        await prefs.set(profile_id, skill_id, enabled)
    return True


async def enrich_prompt(
    base_prompt: str,
    agent_name: str,
    task_text: str,
    profile_id: Optional[str] = None,
    extra_context: str = "",
) -> str:
    """Append profile preferences and matched skills to a base system prompt.

    Never raises; returns base prompt unchanged on failure.
    """
    try:
        if profile_id is None:
            from app.services.profile_service import get_default_profile

            profile_id = (await get_default_profile())["id"]
        from app.services.profile_service import build_preferences_section, get_profile

        profile = await get_profile(profile_id)
        prefs_section = build_preferences_section(profile) if profile else ""
        matched = await match_skills(
            task_text, agent_name, profile_id, extra_context=extra_context
        )
        if matched:
            try:
                from app.workflow.events import emit

                emit(
                    "skills_matched",
                    agent=agent_name,
                    skills=[s["name"] for s in matched],
                )
            except Exception:
                pass
    except Exception as exc:
        logger.warning("Skill enrichment skipped: %s", exc)
        return base_prompt
    sections = [base_prompt]
    if prefs_section:
        sections.append("\n" + prefs_section)
    for skill in matched:
        sections.append(f"\n## 用户技能：{skill['name']}\n{skill['content']}")
    return "\n".join(sections)


async def seed_builtin_skills() -> int:
    """Seed built-in skills when the skills table is empty. Returns count inserted."""
    global _skills_cache
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = SkillRepository(session)
        if await repo.count() > 0:
            return 0
        for item in BUILTIN_SKILLS:
            await repo.create(
                SkillModel(
                    id=f"skill_{uuid.uuid4().hex[:12]}",
                    name=item["name"],
                    description=item["description"],
                    trigger_keywords=json.dumps(item["trigger_keywords"], ensure_ascii=False),
                    agents=json.dumps(item["agents"], ensure_ascii=False),
                    content=item["content"],
                    enabled=True,
                )
            )
    _skills_cache = None
    return len(BUILTIN_SKILLS)
