"""State models for the LangGraph workflow."""

from typing import List, Optional

from pydantic import BaseModel, Field


class SubTask(BaseModel):
    """A single subtask in the research plan."""

    id: str
    description: str
    tool: str = Field(
        description="Tool to use: search | browse | analyze | rag"
    )
    status: str = Field(default="pending", description="pending | running | completed | failed")
    result: Optional[str] = Field(default=None)


class ResearchState(BaseModel):
    """The overall state of a research workflow."""

    task: str = Field(description="The original research task/question")
    plan: List[SubTask] = Field(default_factory=list)
    current_step: int = Field(default=0)
    research_data: List[dict] = Field(default_factory=list)
    sources: List[dict] = Field(
        default_factory=list,
        description="Collected source URLs and titles from research, each: {url, title, snippet}",
    )
    report_draft: str = Field(default="")
    review_score: float = Field(default=0.0)
    review_feedback: str = Field(default="")
    final_report: str = Field(default="")
    errors: List[str] = Field(default_factory=list)
    status: str = Field(default="pending")
    iteration_count: int = Field(default=0)
    max_iterations: int = Field(
        default=3, ge=1, le=10, description="最大评审迭代轮数"
    )
    perspectives: List[str] = Field(
        default_factory=list,
        description="研究视角（STORM 风格，由 Planner 生成）",
    )
    use_rag: bool = Field(default=False, description="Whether to use RAG knowledge base")
    profile_id: Optional[str] = Field(
        default=None,
        description="ID of the user profile whose preferences/skills apply",
    )
    knowledge_report_id: Optional[str] = Field(
        default=None,
        description="ID of the saved report in KnowledgeMemory, populated by formatter_node",
    )
    completed_at: Optional[str] = Field(
        default=None,
        description="ISO-8601 timestamp when the task completed or failed",
    )
    workspace_dir: str = Field(
        default="",
        description="本次研究任务的隔离工作目录绝对路径（空表示未创建）",
    )
    workspace_files: List[str] = Field(
        default_factory=list,
        description="工作目录中的参考文件清单（文件名列表，注入 Agent prompt 用）",
    )
