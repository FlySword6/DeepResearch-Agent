"""WorkspaceManager — per-task isolated working directory.

Each research task gets a private directory under ``root_dir/<task_id>/``.
Uploaded reference files are copied there, and the agent is told (via
prompt injection) it may read files in this directory. File *writes* are
not exposed to the LLM in this feature — the report is written by
ReportService into the same directory.
"""

import logging
import os
import re
import shutil
from typing import List

logger = logging.getLogger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class FileCountLimitExceededError(ValueError):
    """Raised when a workspace already holds the maximum number of files."""


class WorkspaceManager:
    """Creates, inspects, and cleans per-task workspaces."""

    def __init__(self, root_dir: str = "./data/workspaces") -> None:
        self.root_dir = os.path.abspath(root_dir)

    # ------------------------------------------------------------------
    # Path resolution (with traversal safety)
    # ------------------------------------------------------------------

    def _safe_id(self, task_id: str) -> str:
        if not _SAFE_ID.match(task_id):
            raise ValueError(f"非法 task_id: {task_id!r}")
        return task_id

    def workspace_path(self, task_id: str) -> str:
        """Return the absolute workspace path for a task (no side effects)."""
        safe = self._safe_id(task_id)
        return os.path.join(self.root_dir, safe)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def ensure_workspace(self, task_id: str) -> str:
        """Create the workspace directory if absent; return its path."""
        path = self.workspace_path(task_id)
        os.makedirs(path, exist_ok=True)
        logger.info("Workspace ready for task %s at %s", task_id, path)
        return path

    def cleanup(self, task_id: str) -> None:
        """Remove the workspace directory for a task (best-effort)."""
        path = self.workspace_path(task_id)
        if os.path.isdir(path):
            shutil.rmtree(path, ignore_errors=True)
            logger.info("Workspace cleaned for task %s", task_id)

    # ------------------------------------------------------------------
    # File listing / migration
    # ------------------------------------------------------------------

    def list_files(self, task_id: str) -> List[dict]:
        """Return [{name, size_bytes, path}] for files in the workspace."""
        path = self.workspace_path(task_id)
        out: List[dict] = []
        if not os.path.isdir(path):
            return out
        for fname in sorted(os.listdir(path)):
            fpath = os.path.join(path, fname)
            if os.path.isfile(fpath):
                out.append({
                    "name": fname,
                    "size_bytes": os.path.getsize(fpath),
                    "path": fpath,
                })
        return out

    async def save_upload(
        self,
        task_id: str,
        filename: str,
        content: bytes,
        max_bytes: int = 20 * 1024 * 1024,
        max_files: int = 0,
        allowed_exts: tuple = (".pdf", ".md", ".txt", ".csv", ".json", ".docx"),
    ) -> dict:
        """Validate and persist one uploaded file into the task workspace.

        Raises ValueError on unsafe filename / disallowed extension /
        size overrun / file-count overrun (when ``max_files`` > 0).
        Returns the file metadata dict.
        """
        if not filename or filename != os.path.basename(filename):
            raise ValueError(f"非法文件名: {filename!r}")
        # Report files (metadata.json, task_name.txt, rp_*) are written by
        # ReportService into the same directory — reserve those names so an
        # upload cannot forge or shadow report files. NTFS is case-insensitive,
        # so compare lowercased (consistent with the extension check below).
        # NOTE: any future fixed filename written into a workspace by the
        # system must be added to this reservation list.
        lower = filename.lower()
        if lower in ("metadata.json", "task_name.txt") or lower.startswith("rp_"):
            raise ValueError(f"文件名与报告保留命名冲突: {filename!r}")
        ext = os.path.splitext(filename)[1].lower()
        if ext not in allowed_exts:
            raise ValueError(f"不支持的扩展名: {ext}")
        if len(content) > max_bytes:
            raise ValueError(f"文件过大: {len(content)} > {max_bytes}")

        path = self.workspace_path(task_id)
        os.makedirs(path, exist_ok=True)
        # Enforce the per-task file-count cap atomically, right before the
        # write, so concurrent uploads cannot both pass a list-and-write check.
        if max_files > 0 and len(os.listdir(path)) >= max_files:
            raise FileCountLimitExceededError(f"文件数已达上限: {max_files}")
        dest = os.path.join(path, filename)
        with open(dest, "wb") as fh:
            fh.write(content)
        logger.info("Uploaded %s into workspace of %s", filename, task_id)
        return {"name": filename, "size_bytes": len(content), "path": dest}
