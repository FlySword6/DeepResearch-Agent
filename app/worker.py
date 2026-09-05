"""ARQ worker: executes research tasks outside the API process."""

from app.services.task_manager import TaskManager


async def run_research_job(
    ctx,
    task_id: str,
    task_text: str,
    max_iterations: int = 3,
    fmt: str = "markdown",
    use_rag: bool = False,
    profile_id: str = "default",
) -> None:
    manager: TaskManager = ctx.get("task_manager") or TaskManager()
    manager.create_task(task_text, task_id=task_id)

    # Provision the per-task workspace the same way start_research does, so
    # the ARQ path does not fall back to the legacy data/reports/{task_id}.
    from app.config import settings
    from app.services.workspace import WorkspaceManager

    task_info = manager.get_task(task_id)
    if task_info is not None:
        ws = WorkspaceManager(root_dir=settings.WORKSPACE_ROOT)
        task_info.workspace_dir = await ws.ensure_workspace(task_id)
        task_info.workspace_files = [f["name"] for f in ws.list_files(task_id)]

    await manager._run(
        task_id, task_text, max_iterations, fmt, use_rag, profile_id
    )


async def startup(ctx):
    ctx["task_manager"] = TaskManager()


class WorkerSettings:
    functions = [run_research_job]
    on_startup = startup
    max_jobs = 4
    job_timeout = 1800
