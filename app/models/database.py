"""SQLAlchemy ORM models for the DeepResearch-Agent database.

Stores tasks, reports, and task events persistently so data survives
service restarts. Uses SQLAlchemy 2.0 async style for compatibility
with both SQLite (dev) and PostgreSQL (production).
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    and_,
    func,
    or_,
    select,
    text,
)
from sqlalchemy import (
    delete as sa_delete,
)
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase, AsyncAttrs):
    pass


class TaskModel(Base):
    """Persistent research task record."""

    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    report: Mapped[str] = mapped_column(Text, default="")
    review_score: Mapped[float] = mapped_column(Float, default=0.0)
    review_feedback: Mapped[str] = mapped_column(Text, default="")
    errors: Mapped[str] = mapped_column(Text, default="")  # JSON list
    research_data: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    sources: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ReportModel(Base):
    """Persistent report record tied to a task."""

    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    format: Mapped[str] = mapped_column(String(20), default="markdown")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class TaskEventModel(Base):
    """Event log for a task (agent transitions, errors, etc.)."""

    __tablename__ = "task_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    event_data: Mapped[str] = mapped_column(Text, default="{}")  # JSON
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class SkillModel(Base):
    """User-defined skill: structured instruction package injected into agent prompts."""

    __tablename__ = "skills"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    trigger_keywords: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    agents: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    content: Mapped[str] = mapped_column(Text, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True)
    owner_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class UserProfileModel(Base):
    """Per-user research profile: style, domain focus, model override, extra instructions."""

    __tablename__ = "user_profiles"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    writing_style: Mapped[str] = mapped_column(String(32), default="balanced")
    domain_focus: Mapped[str] = mapped_column(String(512), default="")
    preferred_model: Mapped[str] = mapped_column(String(128), default="")
    extra_instructions: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class UserSkillPrefModel(Base):
    """Per-profile enable/disable preference for global skills."""

    __tablename__ = "user_skill_prefs"
    __table_args__ = (UniqueConstraint("profile_id", "skill_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    skill_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True)


class EvolutionDraftModel(Base):
    """Post-task evolution draft: a proposed skill awaiting user confirmation."""

    __tablename__ = "evolution_drafts"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    profile_id: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    review_score: Mapped[float] = mapped_column(Float, default=0.0)
    review_feedback: Mapped[str] = mapped_column(Text, default="")
    lesson: Mapped[str] = mapped_column(Text, default="")
    draft_name: Mapped[str] = mapped_column(String(128), nullable=False)
    draft_description: Mapped[str] = mapped_column(Text, default="")
    draft_trigger_keywords: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    draft_agents: Mapped[str] = mapped_column(Text, default="[]")  # JSON list
    draft_content: Mapped[str] = mapped_column(Text, nullable=False)
    promote_global: Mapped[bool] = mapped_column(default=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


# ---------------------------------------------------------------------------
# Engine & session factory — initialised in lifespan
# ---------------------------------------------------------------------------

_engine = None
_async_session_maker = None


async def _migrate_skills_owner_column(conn) -> None:
    """Add skills.owner_id on pre-existing databases (idempotent)."""
    rows = (await conn.execute(text("PRAGMA table_info(skills)"))).fetchall()
    if not any(row[1] == "owner_id" for row in rows):
        await conn.execute(text("ALTER TABLE skills ADD COLUMN owner_id VARCHAR(64)"))


async def _migrate_task_state_columns(conn) -> None:
    """Add research_data/sources on pre-existing databases (idempotent)."""
    rows = (await conn.execute(text("PRAGMA table_info(tasks)"))).fetchall()
    names = {row[1] for row in rows}
    if "research_data" not in names:
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN research_data TEXT DEFAULT '[]'"))
    if "sources" not in names:
        await conn.execute(text("ALTER TABLE tasks ADD COLUMN sources TEXT DEFAULT '[]'"))
    if "total_tokens" not in names:
        await conn.execute(
            text("ALTER TABLE tasks ADD COLUMN total_tokens INTEGER DEFAULT 0")
        )


def get_db_url() -> str:
    """Return the configured database URL."""
    from app.config import settings

    return settings.DATABASE_URL


async def init_db(db_url: Optional[str] = None) -> None:
    """Create engine, session factory, and all tables."""
    global _engine, _async_session_maker

    url = db_url or get_db_url()
    _engine = create_async_engine(url, echo=False)
    _async_session_maker = async_sessionmaker(_engine, expire_on_commit=False)

    async with _engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await _migrate_skills_owner_column(conn)
        await _migrate_task_state_columns(conn)


async def close_db() -> None:
    """Dispose the database engine."""
    global _engine, _async_session_maker
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _async_session_maker = None


async def get_session():
    """Yield an async session for dependency injection."""
    if _async_session_maker is None:
        raise RuntimeError("Database not initialised — call init_db() first")
    async with _async_session_maker() as session:
        yield session


# ---------------------------------------------------------------------------
# Repository helpers (thin data-access layer)
# ---------------------------------------------------------------------------


class TaskRepository:
    """CRUD operations for tasks."""

    def __init__(self, session):
        self._session = session

    async def create(self, task: TaskModel) -> TaskModel:
        self._session.add(task)
        await self._session.commit()
        return task

    async def get(self, task_id: str) -> Optional[TaskModel]:
        return await self._session.get(TaskModel, task_id)

    async def update(self, task: TaskModel) -> TaskModel:
        await self._session.commit()
        return task

    async def list_recent(self, limit: int = 50) -> List[TaskModel]:
        stmt = select(TaskModel).order_by(TaskModel.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete(self, task_id: str) -> bool:
        task = await self.get(task_id)
        if task is None:
            return False
        await self._session.delete(task)
        await self._session.commit()
        return True


class ReportRepository:
    """CRUD operations for reports."""

    def __init__(self, session):
        self._session = session

    async def create(self, report: ReportModel) -> ReportModel:
        self._session.add(report)
        await self._session.commit()
        return report

    async def get(self, report_id: str) -> Optional[ReportModel]:
        return await self._session.get(ReportModel, report_id)

    async def get_by_task(self, task_id: str) -> List[ReportModel]:
        stmt = select(ReportModel).where(ReportModel.task_id == task_id).order_by(ReportModel.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def delete_by_task(self, task_id: str) -> int:
        stmt = sa_delete(ReportModel).where(ReportModel.task_id == task_id)
        result = await self._session.execute(stmt)
        await self._session.commit()
        return result.rowcount


class TaskEventRepository:
    """Event log for tasks."""

    def __init__(self, session):
        self._session = session

    async def add_event(self, task_id: str, event_type: str, data: Dict[str, Any]) -> TaskEventModel:
        event = TaskEventModel(
            task_id=task_id,
            event_type=event_type,
            event_data=json.dumps(data, default=str),
        )
        self._session.add(event)
        await self._session.commit()
        return event

    async def get_events(self, task_id: str, limit: int = 200) -> List[TaskEventModel]:
        stmt = select(TaskEventModel).where(TaskEventModel.task_id == task_id).order_by(TaskEventModel.id.asc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())


class SkillRepository:
    """CRUD operations for skills."""

    def __init__(self, session):
        self._session = session

    async def create(self, skill: SkillModel) -> SkillModel:
        self._session.add(skill)
        await self._session.commit()
        return skill

    async def get(self, skill_id: str) -> Optional[SkillModel]:
        return await self._session.get(SkillModel, skill_id)

    async def get_by_name(self, name: str) -> Optional[SkillModel]:
        stmt = select(SkillModel).where(SkillModel.name == name)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_all(self) -> List[SkillModel]:
        stmt = select(SkillModel).order_by(SkillModel.created_at.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_for_profile(
        self, profile_id: str, disabled_global_ids: list
    ) -> List[SkillModel]:
        stmt = select(SkillModel).where(
            or_(
                SkillModel.owner_id == profile_id,
                and_(
                    SkillModel.owner_id.is_(None),
                    SkillModel.id.notin_(disabled_global_ids),
                ),
            )
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def count(self) -> int:
        stmt = select(func.count()).select_from(SkillModel)
        result = await self._session.execute(stmt)
        return int(result.scalar() or 0)

    async def update(self, skill: SkillModel) -> SkillModel:
        await self._session.commit()
        return skill

    async def delete(self, skill_id: str) -> bool:
        skill = await self.get(skill_id)
        if skill is None:
            return False
        await self._session.delete(skill)
        await self._session.commit()
        return True


class UserProfileRepository:
    """CRUD operations for user profiles."""

    def __init__(self, session):
        self._session = session

    async def create(self, profile: UserProfileModel) -> UserProfileModel:
        self._session.add(profile)
        await self._session.commit()
        return profile

    async def get(self, profile_id: str) -> Optional[UserProfileModel]:
        return await self._session.get(UserProfileModel, profile_id)

    async def get_by_user(self, user_id: str) -> Optional[UserProfileModel]:
        stmt = select(UserProfileModel).where(UserProfileModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def update(self, profile: UserProfileModel) -> UserProfileModel:
        await self._session.commit()
        return profile


class UserSkillPrefRepository:
    """Per-profile global-skill enable/disable preferences."""

    def __init__(self, session):
        self._session = session

    async def get(self, profile_id: str, skill_id: str) -> Optional[UserSkillPrefModel]:
        stmt = select(UserSkillPrefModel).where(
            UserSkillPrefModel.profile_id == profile_id,
            UserSkillPrefModel.skill_id == skill_id,
        )
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_disabled(self, profile_id: str) -> List[str]:
        stmt = select(UserSkillPrefModel.skill_id).where(
            UserSkillPrefModel.profile_id == profile_id,
            UserSkillPrefModel.enabled.is_(False),
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def set(self, profile_id: str, skill_id: str, enabled: bool) -> None:
        pref = await self.get(profile_id, skill_id)
        if enabled:
            if pref is not None:
                await self._session.delete(pref)
                await self._session.commit()
        else:
            if pref is None:
                self._session.add(
                    UserSkillPrefModel(profile_id=profile_id, skill_id=skill_id, enabled=False)
                )
                await self._session.commit()


class EvolutionDraftRepository:
    """CRUD operations for evolution drafts."""

    def __init__(self, session):
        self._session = session

    async def create(self, draft: EvolutionDraftModel) -> EvolutionDraftModel:
        self._session.add(draft)
        await self._session.commit()
        return draft

    async def get(self, draft_id: str) -> Optional[EvolutionDraftModel]:
        return await self._session.get(EvolutionDraftModel, draft_id)

    async def get_by_task(self, task_id: str) -> Optional[EvolutionDraftModel]:
        stmt = select(EvolutionDraftModel).where(EvolutionDraftModel.task_id == task_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def list_for_profile(
        self, profile_id: str, status: Optional[str] = None
    ) -> List[EvolutionDraftModel]:
        stmt = select(EvolutionDraftModel).where(
            EvolutionDraftModel.profile_id == profile_id
        )
        if status:
            stmt = stmt.where(EvolutionDraftModel.status == status)
        stmt = stmt.order_by(EvolutionDraftModel.created_at.desc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def update(self, draft: EvolutionDraftModel) -> EvolutionDraftModel:
        await self._session.commit()
        return draft
