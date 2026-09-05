"""User profile service: default profile, per-user profiles, preferences text, model override."""

import logging
import uuid
from typing import Any, Dict, Optional

from app.models.database import UserProfileModel, UserProfileRepository

logger = logging.getLogger(__name__)

DEFAULT_PROFILE_ID = "profile_default"

STYLE_LABELS = {
    "academic": "学术严谨",
    "popular": "通俗易懂",
    "business": "商业务实",
    "balanced": "均衡",
}

# profile_id -> serialized profile dict
_profiles_cache: Dict[str, dict] = {}


def invalidate_profiles_cache() -> None:
    _profiles_cache.clear()


def _to_dict(profile: UserProfileModel) -> dict:
    return {
        "id": profile.id,
        "user_id": profile.user_id,
        "display_name": profile.display_name,
        "writing_style": profile.writing_style,
        "domain_focus": profile.domain_focus,
        "preferred_model": profile.preferred_model,
        "extra_instructions": profile.extra_instructions,
    }


async def _load_profile(profile_id: str) -> Optional[dict]:
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = UserProfileRepository(session)
        profile = await repo.get(profile_id)
        return _to_dict(profile) if profile else None


async def get_profile(profile_id: str) -> Optional[dict]:
    """Return a serialized profile, or None if missing. Cached."""
    if profile_id in _profiles_cache:
        return dict(_profiles_cache[profile_id])
    profile = await _load_profile(profile_id)
    if profile is not None:
        _profiles_cache[profile_id] = profile
    return dict(profile) if profile else None


async def _create_profile(profile_id: str, user_id: Optional[str]) -> dict:
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = UserProfileRepository(session)
        created = await repo.create(UserProfileModel(id=profile_id, user_id=user_id))
    invalidate_profiles_cache()
    return _to_dict(created)


async def get_default_profile() -> dict:
    """Return the default (anonymous) profile, creating it if missing."""
    profile = await get_profile(DEFAULT_PROFILE_ID)
    if profile is None:
        profile = await _create_profile(DEFAULT_PROFILE_ID, None)
    return profile


async def get_or_create_profile(user_id: str) -> dict:
    """Return the profile bound to an authenticated user, creating it if missing."""
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = UserProfileRepository(session)
        existing = await repo.get_by_user(user_id)
        if existing is not None:
            profile = _to_dict(existing)
            _profiles_cache[profile["id"]] = profile
            return profile
    return await _create_profile(f"profile_{uuid.uuid4().hex[:12]}", user_id)


async def get_effective_profile(user: Optional[dict]) -> dict:
    """Anonymous -> default profile; authenticated -> the user's profile."""
    if user and user.get("id"):
        return await get_or_create_profile(user["id"])
    return await get_default_profile()


async def update_profile(profile_id: str, data: Dict[str, Any]) -> Optional[dict]:
    """Update profile fields. Returns updated dict, or None if missing."""
    from app.models.database import _async_session_maker

    async with _async_session_maker() as session:
        repo = UserProfileRepository(session)
        profile = await repo.get(profile_id)
        if profile is None:
            return None
        if "display_name" in data:
            profile.display_name = data["display_name"]
        if "writing_style" in data:
            profile.writing_style = data["writing_style"]
        if "domain_focus" in data:
            profile.domain_focus = data["domain_focus"]
        if "preferred_model" in data:
            profile.preferred_model = data["preferred_model"]
        if "extra_instructions" in data:
            profile.extra_instructions = data["extra_instructions"]
        updated = await repo.update(profile)
        await session.refresh(updated)
    _profiles_cache.pop(profile_id, None)
    return _to_dict(updated)


async def get_profile_model(profile_id: Optional[str]) -> Optional[str]:
    """Return the profile's preferred model, or None."""
    pid = profile_id or DEFAULT_PROFILE_ID
    profile = await get_profile(pid)
    return (profile or {}).get("preferred_model") or None


ROLE_MODEL_SETTINGS = {
    "planner": "LLM_MODEL_PLANNER",
    "researcher": "LLM_MODEL_RESEARCHER",
    "writer": "LLM_MODEL_WRITER",
    "reviewer": "LLM_MODEL_REVIEWER",
}


async def get_agent_model(agent: str, profile_id: Optional[str]) -> str:
    """Resolve the model for a role: profile override > role setting > default."""
    profile_model = await get_profile_model(profile_id)
    if profile_model:
        return profile_model
    from app.config import settings

    env_key = ROLE_MODEL_SETTINGS.get(agent)
    if env_key:
        configured = getattr(settings, env_key, "")
        if configured:
            return configured
    return "gpt-4o"


def build_preferences_section(profile: dict) -> str:
    """Build the `## 用户偏好` section injected into agent prompts."""
    style = STYLE_LABELS.get(profile.get("writing_style", "balanced"), "均衡")
    lines = ["## 用户偏好", f"- 写作风格：{style}"]
    domains = (profile.get("domain_focus") or "").strip()
    if domains:
        lines.append(f"- 领域聚焦：{domains}")
    extra = (profile.get("extra_instructions") or "").strip()
    if extra:
        lines.append("")
        lines.append(extra)
    return "\n".join(lines)
