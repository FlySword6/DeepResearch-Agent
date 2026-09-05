"""ToolRouter — central dispatcher for tool calls.

Maps tool names to their implementations so agents can request tools by
name without knowing the concrete class.
"""

import logging
from typing import Any, Dict, List

from app.tools.base import BaseTool, ToolResult
from app.tools.browser import BrowserTool
from app.tools.memory import MemoryTool
from app.tools.python_executor import DisabledPythonTool, PythonTool
from app.tools.rag_retriever import RAGRetrieverTool
from app.tools.search import SearchTool
from app.tools.workspace_reader import WorkspaceReaderTool

logger = logging.getLogger(__name__)

_DEFAULT_TOOL_NAME_MAP: Dict[str, str] = {
    "search": "search",
    "browse": "browse",
    "analyze": "analyze",
    "rag": "rag",
    "read_workspace": "read_workspace",
}


class ToolRouter:
    """Routes named tool calls to the correct ``BaseTool`` implementation.

    Typical usage::

        router = ToolRouter()
        result = await router.execute("search", query="quantum computing")
        print(result.data)
    """

    def __init__(self) -> None:
        self._tools: Dict[str, BaseTool] = {}
        self._register_defaults()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _register_defaults(self) -> None:
        from app.config import settings

        self.register("search", SearchTool())
        self.register("browse", BrowserTool())
        if settings.ENABLE_PYTHON_TOOL:
            self.register("analyze", PythonTool())
        else:
            self.register("analyze", DisabledPythonTool())
        self.register("memory", MemoryTool())
        self.register("rag", RAGRetrieverTool())
        self.register("read_workspace", WorkspaceReaderTool())

    def register(self, name: str, tool: BaseTool) -> None:
        """Register a tool under *name*."""
        self._tools[name] = tool
        logger.debug("Registered tool '%s': %s", name, type(tool).__name__)

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> BaseTool:
        """Return the tool registered under *name*, or raise ``ValueError``."""
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError(
                f"Tool '{name}' not found. Available: {list(self._tools.keys())}"
            )
        return tool

    def list_tools(self) -> List[Dict[str, str]]:
        """Return a summary list of every registered tool."""
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(self, name: str, **params: Any) -> ToolResult:
        """Look up *name* and execute it with *params*."""
        tool = self.get_tool(name)
        logger.info("Executing tool '%s' with params: %s", name, params)
        return await tool.execute(**params)

    @staticmethod
    def resolve_tool_name(subtask_tool: str) -> str:
        """Map a SubTask.tool value to a registered tool name.

        If the value is already a known key it is returned as-is; otherwise
        the static map is consulted.
        """
        return _DEFAULT_TOOL_NAME_MAP.get(subtask_tool, subtask_tool)
