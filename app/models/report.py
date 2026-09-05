"""用于存储生成后研究报告的模型。"""

from typing import List, Optional
from pydantic import BaseModel, Field
from datetime import datetime


class ReportSection(BaseModel):
    """报告中的单个章节。"""

    title: str
    content: str
    subsections: List["ReportSection"] = Field(default_factory=list)


class ReportSource(BaseModel):
    """报告中的单条引用来源。"""

    url: str
    title: str
    snippet: str = Field(default="")


class Report(BaseModel):
    """完整研究报告模型。"""

    task_id: str
    title: str = Field(default="")
    abstract: str = Field(default="")
    sections: List[ReportSection] = Field(default_factory=list)
    sources: List[ReportSource] = Field(default_factory=list)
    conclusion: str = Field(default="")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    version: int = Field(default=1)
