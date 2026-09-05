"""Agent 工具调用和响应模型。"""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ToolCall(BaseModel):
    """Agent 发起的一次工具调用。"""

    tool_name: str = Field(description="要调用的工具名称")
    arguments: Dict[str, Any] = Field(default_factory=dict)
    call_id: str = Field(default="")


class ToolResponse(BaseModel):
    """工具调用返回结果。"""

    tool_name: str
    result: Any = None
    error: Optional[str] = None
    call_id: str = Field(default="")
