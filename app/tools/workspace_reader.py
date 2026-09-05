"""WorkspaceReaderTool — reads a reference file from a task's workspace.

The task workspace holds uploaded reference files (see WorkspaceManager).
This tool lets an agent (e.g. the Researcher) read one of those files by
name so it can actually consume the uploaded content. Path traversal and
absolute paths are rejected so the tool can never read outside the
workspace.
"""

import logging
import os
from typing import Any

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

MAX_CONTENT_CHARS = 8000

READ_WORKSPACE_PARAMETERS = {
    "type": "object",
    "properties": {
        "filename": {
            "type": "string",
            "description": "文件名",
        },
    },
    "required": ["filename"],
}


class WorkspaceReaderTool(BaseTool):
    """Reads a reference file from the task workspace and returns its content."""

    name = "read_workspace"
    description = (
        "读取工作目录（workspace）中的参考文件内容。"
        "filename 参数传入文件名（例如 'ref.md'），返回文件内容供研究使用。"
    )
    parameters = READ_WORKSPACE_PARAMETERS

    async def execute(
        self,
        filename: str = "",
        workspace_dir: str = "",
        **_kwargs: Any,
    ) -> ToolResult:
        """Read *filename* from *workspace_dir* and return its content.

        Security: the resolved path must stay inside *workspace_dir*.
        Traversal (``../``), absolute paths, and subdirectory escapes are
        rejected before any file is opened.
        """
        if not workspace_dir or not isinstance(workspace_dir, str):
            return ToolResult(
                success=False,
                error="缺少 workspace_dir 参数（工作目录未创建或未传入）。",
            )
        if not filename or not isinstance(filename, str):
            return ToolResult(
                success=False,
                error="缺少 filename 参数（需要指定要读取的文件名）。",
            )
        if filename != os.path.basename(filename):
            return ToolResult(
                success=False,
                error=f"非法文件名（不允许路径或目录穿越）: {filename!r}",
            )

        ws_real = os.path.realpath(workspace_dir)
        candidate = os.path.realpath(os.path.join(ws_real, filename))
        try:
            inside = os.path.commonpath([ws_real, candidate]) == ws_real
        except ValueError:
            inside = False
        if not inside:
            return ToolResult(
                success=False,
                error=f"非法文件名（超出工作目录范围）: {filename!r}",
            )

        if not os.path.isfile(candidate):
            return ToolResult(
                success=False,
                error=f"文件不存在: {filename}",
            )

        try:
            with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
                content = fh.read()
        except OSError as exc:
            logger.warning("Failed to read workspace file %s: %s", filename, exc)
            return ToolResult(
                success=False,
                error=f"读取文件失败: {exc}",
            )

        truncated = len(content) > MAX_CONTENT_CHARS
        original_len = len(content)
        if truncated:
            content = content[:MAX_CONTENT_CHARS] + "\n...[内容过长，已截断]"

        return ToolResult(
            success=True,
            data={
                "filename": filename,
                "content": content,
            },
            metadata={
                "workspace_dir": ws_real,
                "truncated": truncated,
                "length": original_len,
            },
        )
