"""API request/response Pydantic models."""

from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class ResearchRequest(BaseModel):
    """Request model for starting a research task."""

    task: str = Field(..., min_length=1, max_length=5000, description="The research topic or question")
    max_iterations: int = Field(default=3, ge=1, le=10, description="Maximum refinement iterations")


class ResearchResponse(BaseModel):
    """Response model after research completes."""

    task_id: str
    status: str
    final_report: str = Field(default="")
    review_score: float = Field(default=0.0)
    review_feedback: str = Field(default="")
    errors: List[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    version: str = "1.0.0"


class TaskStatusResponse(BaseModel):
    """Status response for a running/completed task."""

    task_id: str
    status: str = Field(description="pending | running | completed | failed")
    current_step: int = Field(default=0)
    total_steps: int = Field(default=0)
    progress: float = Field(default=0.0, ge=0.0, le=1.0)
    errors: List[str] = Field(default_factory=list)


class SettingsResponse(BaseModel):
    """Response for GET /api/settings."""

    configured: bool
    provider: str = "openai"
    api_key: str = ""
    model: str = "gpt-4o"
    base_url: str = ""
    embedding_model: str = "text-embedding-v3"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_configured: bool = False
    reranker_enabled: bool = False
    reranker_api_key: str = ""
    reranker_base_url: str = ""
    reranker_model: str = ""


class SettingsUpdateRequest(BaseModel):
    """Request body for POST /api/settings."""

    provider: str = Field(default="openai", pattern=r"^(openai|anthropic)$")
    api_key: str = Field(..., min_length=1)
    model: str = Field(..., min_length=1)
    base_url: str = Field(default="")
    embedding_model: Optional[str] = Field(default=None, min_length=1)
    embedding_api_key: Optional[str] = Field(default=None, min_length=1)
    embedding_base_url: Optional[str] = None
    reranker_enabled: Optional[bool] = None
    reranker_api_key: Optional[str] = None
    reranker_base_url: Optional[str] = None
    reranker_model: Optional[str] = None


class SettingsTestResult(BaseModel):
    """Result from testing an LLM connection."""

    success: bool
    message: str = ""


VALID_AGENT_NAMES = r"^(planner|researcher|writer|reviewer)$"


class SkillCreate(BaseModel):
    """Request body for creating a skill."""

    name: str = Field(..., min_length=1, max_length=128)
    description: str = Field(default="", max_length=500)
    trigger_keywords: List[str] = Field(default_factory=list)
    agents: List[str] = Field(default_factory=list)
    content: str = Field(..., min_length=1)
    enabled: bool = Field(default=True)


class SkillUpdate(BaseModel):
    """Request body for updating a skill (partial update)."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = Field(default=None, max_length=500)
    trigger_keywords: Optional[List[str]] = None
    agents: Optional[List[str]] = None
    content: Optional[str] = Field(default=None, min_length=1)
    enabled: Optional[bool] = None


class SkillResponse(BaseModel):
    """Skill record returned by the API."""

    id: str
    owner_id: Optional[str] = None
    name: str
    description: str = ""
    trigger_keywords: List[str] = Field(default_factory=list)
    agents: List[str] = Field(default_factory=list)
    content: str = ""
    enabled: bool = True
    enabled_for_me: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SkillMatchRequest(BaseModel):
    """Request body for testing which skills match a task."""

    task: str = Field(..., min_length=1)
    agent: Optional[str] = Field(
        default=None, pattern=VALID_AGENT_NAMES
    )


class SkillAgentMatch(BaseModel):
    """Matched skills for a single agent in the match preview."""

    agent: str
    skills: List[SkillResponse] = Field(default_factory=list)


class SkillMatchResponse(BaseModel):
    """Response with matched skills."""

    skills: List[SkillResponse] = Field(default_factory=list)
    matches: List[SkillAgentMatch] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    """Current user profile."""

    id: str
    user_id: Optional[str] = None
    display_name: str = ""
    writing_style: str = "balanced"
    domain_focus: str = ""
    preferred_model: str = ""
    extra_instructions: str = ""


class ProfileUpdateRequest(BaseModel):
    """Partial update for the current user profile."""

    display_name: Optional[str] = Field(default=None, max_length=128)
    writing_style: Optional[str] = Field(
        default=None, pattern=r"^(academic|popular|business|balanced)$"
    )
    domain_focus: Optional[str] = Field(default=None, max_length=512)
    preferred_model: Optional[str] = Field(default=None, max_length=128)
    extra_instructions: Optional[str] = None


class SkillPrefRequest(BaseModel):
    """Body for enabling/disabling a global skill for the current profile."""

    enabled: bool


class EvolutionDraftResponse(BaseModel):
    """Evolution draft returned by the API."""

    id: str
    task_id: str = ""
    review_score: float = 0.0
    review_feedback: str = ""
    lesson: str = ""
    draft_name: str = ""
    draft_description: str = ""
    draft_trigger_keywords: List[str] = Field(default_factory=list)
    draft_agents: List[str] = Field(default_factory=list)
    draft_content: str = ""
    promote_global: bool = False
    status: str = "pending"
    created_at: Optional[datetime] = None


class EvolutionDraftEdit(BaseModel):
    """Optional edits applied when accepting a draft."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=128)
    description: Optional[str] = None
    trigger_keywords: Optional[List[str]] = None
    agents: Optional[List[str]] = None
    content: Optional[str] = Field(default=None, min_length=1)


class EvolutionAcceptRequest(BaseModel):
    """Body for accepting a draft."""

    promote_global: bool = False
    edits: Optional[EvolutionDraftEdit] = None
