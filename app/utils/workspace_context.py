"""Build the 'workspace environment' instruction injected into agent prompts."""

from typing import List


def build_workspace_instruction(
    workspace_dir: str,
    files: List[str],
    relative_hint: str = "",
) -> str:
    """Return a compact instruction block telling the agent about its workspace.

    Intentionally read-only guidance: the agent may reference/read files in
    the workspace; file *generation* is handled by ReportService, not by the
    model writing to arbitrary paths.
    """
    lines = [
        "【工作环境指令】",
        f"工作目录: {relative_hint or workspace_dir}",
    ]
    if files:
        lines.append("参考文件（研究时优先阅读）:")
        lines.extend(f"  - {fname}" for fname in files)
    else:
        lines.append("工作目录中没有参考文件。")
    lines.append("研究过程中，如需要读取或引用参考文件，必须使用上面的工作目录路径。")
    return "\n".join(lines)
