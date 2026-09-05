"""Service for generating, formatting, and retrieving research reports."""

import json
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.utils.markdown_utils import format_report, extract_sources_from_report
from app.utils.pdf_utils import generate_pdf

logger = logging.getLogger(__name__)


class ReportService:
    """Service for generating, formatting, and retrieving reports.

    Handles saving reports in multiple formats (markdown, PDF),
    listing available reports, and retrieving report content.
    """

    def __init__(self, output_dir: str = "./data/reports") -> None:
        """Initialize the service with an output directory.

        Args:
            output_dir: Directory where reports are stored.
        """
        self._output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def save_report(
        self,
        task_id: str,
        content: str,
        fmt: str = "markdown",
        task_display: str = "",
        sources: Optional[List[Dict[str, str]]] = None,
        workspace_dir: str = "",
    ) -> Dict[str, Any]:
        """Save a report in the specified format(s).

        Files are stored under ``{output_dir}/{task_id}/`` (or under
        ``workspace_dir`` when provided).  The default directory
        name is the *task_id* so that ``get_report(task_id)`` can find
        it directly.

        Args:
            task_id: Unique identifier for the research task.
            content: The report content (raw or pre-formatted).
            fmt: Output format — ``"markdown"``, ``"pdf"``, or ``"both"``.
            task_display: Human-readable task name for the report title.
            sources: Optional list of source dicts with ``url`` and ``title`` keys.
            workspace_dir: Optional directory where the report is saved
                (falls back to ``{output_dir}/{task_id}`` when empty).

        Returns:
            A dict with paths and metadata:
            ``{"report_id", "task_id", "markdown_path", "pdf_path", "created_at"}``.
        """
        report_id = self._generate_report_id()
        base_dir = workspace_dir or os.path.join(self._output_dir, task_id)
        os.makedirs(base_dir, exist_ok=True)
        timestamp = datetime.now().isoformat()

        # Build metadata
        metadata: Dict[str, Any] = {
            "report_id": report_id,
            "task_id": task_id,
            "task_display": task_display,
            "created_at": timestamp,
            "fmt": fmt,
        }

        formatted = format_report(task_display or task_id, content, sources=sources)

        markdown_path: Optional[str] = None
        pdf_path: Optional[str] = None

        # Save markdown
        if fmt in ("markdown", "both"):
            markdown_path = self._write_markdown(base_dir, report_id, formatted)
            metadata["markdown_path"] = markdown_path

        # Save PDF
        if fmt in ("pdf", "both"):
            try:
                pdf_path = await self._write_pdf(base_dir, report_id, formatted)
                metadata["pdf_path"] = pdf_path
            except Exception as exc:
                logger.error("Failed to generate PDF for report %s: %s", report_id, exc)
                metadata["pdf_error"] = str(exc)

        # Write metadata file
        self._write_metadata(base_dir, metadata)

        return metadata

    async def get_report(self, task_id: str, fmt: str = "markdown") -> Optional[str]:
        """Retrieve report content.

        Args:
            task_id: The research task ID.
            fmt: ``"markdown"`` or ``"pdf"``.

        Returns:
            The report content as a string (markdown) or the file path (PDF),
            or ``None`` if not found.
        """
        reports_dir = self._resolve_task_dir(task_id)
        if not os.path.isdir(reports_dir):
            return None

        # Prefer the recorded report file (metadata) or a report-named file
        # (rp_*) over arbitrary .md/.pdf — so uploaded reference files in the
        # workspace never shadow the generated report.
        meta = self._read_metadata(task_id)

        if fmt == "pdf":
            for path in self._preferred_report_paths(reports_dir, meta, ".pdf"):
                if path and os.path.isfile(path):
                    return path
            return None

        # Return the markdown content
        for path in self._preferred_report_paths(reports_dir, meta, ".md"):
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    return fh.read()
            except Exception:
                continue

        return None

    def list_reports(self, limit: int = 20) -> List[Dict[str, Any]]:
        """List all generated reports, newest first.

        Scans both the legacy output directory and the per-task workspace
        root, de-duplicating by task_id.

        Args:
            limit: Maximum number of reports to return.

        Returns:
            A list of report metadata dicts.
        """
        reports: List[Dict[str, Any]] = []

        self._scan_task_dir(reports, self._output_dir, limit)
        if len(reports) >= limit:
            return reports

        # Reports may live under the workspace root instead of the legacy dir.
        try:
            from app.config import settings
            from app.services.workspace import WorkspaceManager

            ws_root = WorkspaceManager(root_dir=settings.WORKSPACE_ROOT).root_dir
            self._scan_task_dir(reports, ws_root, limit)
        except Exception:
            pass

        return reports

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _generate_report_id(self) -> str:
        """Generate a unique report ID like ``rp_xxx``."""
        return f"rp_{uuid.uuid4().hex[:12]}"

    def _preferred_report_paths(
        self,
        reports_dir: str,
        meta: Optional[Dict[str, Any]],
        ext: str,
    ) -> List[str]:
        """Ordered candidate report file paths (report first, uploads last).

        ``meta`` is the task's ``metadata.json`` dict (or ``None``). The
        recorded ``markdown_path``/``pdf_path`` is trusted first, then files
        matching the generated ``rp_*.<ext>`` naming, then any file with the
        extension (so a report saved without metadata can still be found).
        Metadata paths pointing outside the task dir are ignored so a forged
        ``metadata.json`` cannot read arbitrary files.
        """
        candidates: List[str] = []
        key = "markdown_path" if ext == ".md" else "pdf_path"
        if meta and meta.get(key):
            meta_path = meta[key]
            if self._path_within(meta_path, reports_dir):
                candidates.append(meta_path)

        for fname in sorted(os.listdir(reports_dir)):
            if fname.startswith("rp_") and fname.endswith(ext):
                candidates.append(os.path.join(reports_dir, fname))

        for fname in sorted(os.listdir(reports_dir)):
            fpath = os.path.join(reports_dir, fname)
            if fname.endswith(ext) and fpath not in candidates:
                candidates.append(fpath)
        return candidates

    def _path_within(self, path: str, base_dir: str) -> bool:
        """Return True if ``path`` (resolved) is inside ``base_dir`` (resolved)."""
        base = os.path.realpath(base_dir)
        try:
            target = os.path.realpath(path)
            # commonpath raises ValueError when paths are on different drives
            # (Windows) — treat that as "outside" rather than propagating.
            return os.path.commonpath([base, target]) == base
        except ValueError:
            return False
        except Exception:
            return False

    def _resolve_task_dir(self, task_id: str) -> str:
        """Return the dir where a task's report lives (legacy or workspace)."""
        legacy = os.path.join(self._output_dir, task_id)
        if os.path.isdir(legacy):
            return legacy
        try:
            from app.config import settings
            from app.services.workspace import WorkspaceManager

            ws_dir = WorkspaceManager(root_dir=settings.WORKSPACE_ROOT).workspace_path(task_id)
            if os.path.isdir(ws_dir):
                return ws_dir
        except Exception:
            pass
        return legacy

    def _scan_task_dir(
        self, reports: List[Dict[str, Any]], root_dir: str, limit: int
    ) -> None:
        """Append report entries from one root dir, de-duplicating by task_id."""
        if not os.path.isdir(root_dir):
            return

        seen = {r.get("task_id") for r in reports}
        for task_dir in sorted(os.listdir(root_dir), reverse=True):
            task_path = os.path.join(root_dir, task_dir)
            if not os.path.isdir(task_path):
                continue
            if task_dir in seen:
                continue

            # A dir is only a report if it has report markers: metadata.json
            # (always written by save_report), task_name.txt (written alongside
            # rp_* files), or a generated rp_* report file. Uploaded reference
            # files alone do not make a report.
            has_report_marker = any(
                f == "metadata.json"
                or f == "task_name.txt"
                or (f.startswith("rp_") and f.endswith((".md", ".pdf")))
                for f in os.listdir(task_path)
            )
            if not has_report_marker:
                continue

            meta = self._read_metadata(task_dir)
            if meta:
                reports.append(meta)
            else:
                # Minimal metadata from report-named files only.
                md_files = [f for f in os.listdir(task_path) if f.startswith("rp_") and f.endswith(".md")]
                pdf_files = [f for f in os.listdir(task_path) if f.startswith("rp_") and f.endswith(".pdf")]
                reports.append({
                    "task_id": task_dir,
                    "report_id": task_dir,
                    "markdown_path": str(os.path.join(task_path, md_files[0])) if md_files else None,
                    "pdf_path": str(os.path.join(task_path, pdf_files[0])) if pdf_files else None,
                })

            if len(reports) >= limit:
                return

    def _write_markdown(self, task_path: str, report_id: str, content: str) -> str:
        """Write markdown content to disk and return the file path.

        File is stored at ``{task_path}/{report_id}.md``.
        """
        os.makedirs(task_path, exist_ok=True)
        fpath = os.path.join(task_path, f"{report_id}.md")
        with open(fpath, "w", encoding="utf-8") as fh:
            fh.write(content)
        logger.info("Markdown report saved: %s", fpath)

        # Also save a copy with the original task name for history lookups
        from app.utils.markdown_utils import format_report
        # Extract first heading as task name
        task_name = os.path.basename(task_path)
        for line in content.split("\n"):
            stripped = line.strip()
            if stripped.startswith("# "):
                task_name = stripped[2:].strip()
                break
        # Write a simple mapping file so history can restore task names
        name_file = os.path.join(task_path, "task_name.txt")
        try:
            with open(name_file, "w", encoding="utf-8") as fh:
                fh.write(task_name)
        except Exception:
            pass

        return fpath

    async def _write_pdf(self, task_path: str, report_id: str, content: str) -> str:
        """Generate and write PDF, returning the file path.

        File is stored at ``{task_path}/{report_id}.pdf``.
        """
        os.makedirs(task_path, exist_ok=True)
        fpath = os.path.join(task_path, f"{report_id}.pdf")
        await generate_pdf(content, fpath)
        logger.info("PDF report saved: %s", fpath)
        return fpath

    def _write_metadata(self, task_dir: str, metadata: Dict[str, Any]) -> None:
        """Write metadata JSON for a report under the task directory."""
        os.makedirs(task_dir, exist_ok=True)
        meta_path = os.path.join(task_dir, "metadata.json")
        try:
            with open(meta_path, "w", encoding="utf-8") as fh:
                json.dump(metadata, fh, indent=2, default=str)
        except Exception as exc:
            logger.warning("Failed to write metadata for %s: %s", task_dir, exc)

    def _read_metadata(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Read metadata JSON for a task, if it exists."""
        meta_path = os.path.join(self._resolve_task_dir(task_id), "metadata.json")
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as fh:
                    return json.load(fh)
            except Exception:
                pass
        return None
