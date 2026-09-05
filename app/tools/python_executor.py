"""PythonTool — safely executes Python code in a restricted sandbox.

Captures stdout/stderr and enforces a configurable timeout.
Dangerous builtins (os, subprocess, shutil, etc.) are excluded from the
execution namespace.
"""

import asyncio
import builtins
import io
import logging
import time
import traceback
from contextlib import redirect_stdout, redirect_stderr
from typing import Any

from app.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

PYTHON_PARAMETERS = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": "The Python code to execute",
        },
        "timeout": {
            "type": "integer",
            "description": "Maximum execution time in seconds",
            "default": 30,
        },
    },
    "required": ["code"],
}

# Restricted builtins — remove dangerous functions but keep useful ones.
_SAFE_BUILTINS: dict = {
    "abs": abs,
    "all": all,
    "any": any,
    "ascii": ascii,
    "bin": bin,
    "bool": bool,
    "bytearray": bytearray,
    "bytes": bytes,
    "chr": chr,
    "complex": complex,
    "dict": dict,
    "dir": dir,
    "divmod": divmod,
    "enumerate": enumerate,
    "filter": filter,
    "float": float,
    "format": format,
    "frozenset": frozenset,
    "getattr": getattr,
    "hasattr": hasattr,
    "hash": hash,
    "hex": hex,
    "id": id,
    "int": int,
    "isinstance": isinstance,
    "issubclass": issubclass,
    "iter": iter,
    "len": len,
    "list": list,
    "map": map,
    "max": max,
    "min": min,
    "next": next,
    "object": object,
    "oct": oct,
    "ord": ord,
    "pow": pow,
    "print": print,
    "range": range,
    "repr": repr,
    "reversed": reversed,
    "round": round,
    "set": set,
    "slice": slice,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "super": super,
    "tuple": tuple,
    "type": type,
    "zip": zip,
    "True": True,
    "False": False,
    "None": None,
}

# Names that are *blocked* even if accessible via `__import__`.
_BLOCKED_MODULES = frozenset({
    "os",
    "subprocess",
    "shutil",
    "signal",
    "ctypes",
    "multiprocessing",
    "socket",
})


def _safe_import(
    name: str,
    globals=None,
    locals=None,
    fromlist=(),
    level=0,
):
    """Block dangerous top-level modules; delegate everything else."""
    root = name.split(".")[0]
    if root in _BLOCKED_MODULES:
        raise ImportError(f"module '{name}' is blocked in the analysis sandbox")
    return builtins.__import__(name, globals, locals, fromlist, level)


class PythonTool(BaseTool):
    """Executes Python code in a restricted sandbox with timeout."""

    name = "analyze"
    description = "Execute Python code for data analysis and computation"
    parameters = PYTHON_PARAMETERS

    async def execute(
        self,
        code: str,
        timeout: int = 30,
        workspace_dir: str = "",
        **_kwargs: Any,
    ) -> ToolResult:
        """Execute *code* and return captured stdout/stderr."""
        if not code or not isinstance(code, str):
            return ToolResult(
                success=False,
                error="A valid 'code' string parameter is required.",
            )

        start = time.monotonic()
        try:
            stdout, stderr = await asyncio.wait_for(
                self._run_in_executor(code, workspace_dir=workspace_dir),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            return ToolResult(
                success=False,
                error=f"Execution timed out after {timeout}s",
                metadata={"execution_time": round(elapsed, 3), "timed_out": True},
            )
        except Exception as exc:
            elapsed = time.monotonic() - start
            return ToolResult(
                success=False,
                error=str(exc),
                metadata={"execution_time": round(elapsed, 3)},
            )

        elapsed = time.monotonic() - start
        return ToolResult(
            success=True,
            data={
                "stdout": stdout,
                "stderr": stderr,
                "execution_time": round(elapsed, 3),
            },
            metadata={"execution_time": round(elapsed, 3)},
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _run_in_executor(self, code: str, workspace_dir: str = "") -> tuple:
        """Run the code in a thread-pool executor to avoid blocking."""

        def _run() -> tuple:
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()

            # Build a restricted global namespace
            restricted_globals: dict = {
                "__builtins__": {**_SAFE_BUILTINS, "__import__": _safe_import},
                "__name__": "__sandbox__",
                "WORKSPACE_DIR": workspace_dir,
            }

            try:
                compiled = compile(code, "<sandbox>", "exec")

                with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                    exec(compiled, restricted_globals)

            except Exception:
                # Write traceback to stderr buffer
                traceback.print_exc(file=stderr_buf)

            return stdout_buf.getvalue(), stderr_buf.getvalue()

        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, _run)


class DisabledPythonTool(BaseTool):
    """Placeholder returned when ENABLE_PYTHON_TOOL is false."""

    name = "analyze"
    description = "Python 分析工具（默认禁用，需设置 ENABLE_PYTHON_TOOL=true）"
    parameters = PYTHON_PARAMETERS

    async def execute(self, **kwargs: Any) -> ToolResult:
        return ToolResult(
            success=False,
            error="analyze 工具已禁用：请设置 ENABLE_PYTHON_TOOL=true 后重启服务",
        )
