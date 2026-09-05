"""Abstract base class and result model for all tools."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    """Standard result wrapper returned by every tool execution."""

    success: bool = True
    data: Any = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BaseTool(ABC):
    """Abstract interface every tool must implement."""

    name: str
    description: str
    parameters: dict  # JSON Schema describing accepted parameters

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with the given keyword arguments."""
        ...
