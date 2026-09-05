"""FastAPI application entry point for DeepResearch-Agent.

Provides REST API for:
- POST /api/research - start a research task
- GET /api/research/{task_id}/stream - SSE stream of agent events
- GET /api/research/{task_id} - task status
- GET /api/reports/{task_id} - download report
- GET /api/history - list historical tasks
- GET /health - health check
- POST /api/auth/register - user registration
- POST /api/auth/login - user login
"""

import asyncio
import json
import logging
import math
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, AsyncGenerator, Dict, List, Literal, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from pydantic import BaseModel, Field

from app.config import settings
from app.auth.dependencies import get_optional_user
from app.middleware import register_middleware
from app.models.database import init_db, close_db
from app.models.schemas import (
    EvolutionAcceptRequest,
    EvolutionDraftResponse,
    HealthResponse,
    ProfileResponse,
    ProfileUpdateRequest,
    ResearchResponse,
    SettingsResponse,
    SettingsTestResult,
    SettingsUpdateRequest,
    SkillCreate,
    SkillMatchRequest,
    SkillMatchResponse,
    SkillPrefRequest,
    SkillResponse,
    SkillUpdate,
    TaskStatusResponse,
)
from app.services.config_service import (
    DEFAULT_BASE_URLS,
    RuntimeLLMConfig,
    get_active_config,
    load_runtime_config,
    mask_api_key,
    save_runtime_config,
)
from app.services.report_service import ReportService
from app.services.profile_service import (
    get_effective_profile,
    update_profile as update_user_profile,
)
from app.services.evolution_service import accept_draft, list_drafts, reject_draft
from app.services.skill_service import (
    DuplicateSkillNameError,
    InvalidSkillError,
    create_skill,
    delete_skill,
    list_skills_for_profile,
    match_skills,
    seed_builtin_skills,
    set_skill_pref,
    update_skill,
)
from app.services.task_manager import TaskManager
from app.utils.logger import setup_logging
from app.utils.pdf_utils import generate_pdf

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Global services
# ---------------------------------------------------------------------------

_task_manager = TaskManager()
_report_service = ReportService()

# ---------------------------------------------------------------------------
# Runtime LLM config cache (avoid file reads on every LLM call)
# ---------------------------------------------------------------------------

_runtime_config_cache: Optional[RuntimeLLMConfig] = None


def _get_cached_config() -> RuntimeLLMConfig:
    global _runtime_config_cache
    if _runtime_config_cache is None:
        _runtime_config_cache = get_active_config()
    return _runtime_config_cache


def _invalidate_config_cache() -> None:
    global _runtime_config_cache
    _runtime_config_cache = None


async def _test_llm_connection(config: RuntimeLLMConfig) -> SettingsTestResult:
    """Test an LLM configuration by making a minimal API call."""
    try:
        if config.provider == "openai":
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=config.api_key, base_url=config.base_url)
            await client.chat.completions.create(
                model=config.model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5,
            )
        elif config.provider == "anthropic":
            from anthropic import AsyncAnthropic

            client = AsyncAnthropic(api_key=config.api_key)
            await client.messages.create(
                model=config.model,
                max_tokens=5,
                messages=[{"role": "user", "content": "ping"}],
            )
        return SettingsTestResult(success=True, message="连接测试成功")
    except Exception as exc:
        err_msg = str(exc)
        if "401" in err_msg or "authentication_error" in err_msg or "Unauthorized" in err_msg:
            return SettingsTestResult(success=False, message="API Key 无效，请检查后重试")
        if "404" in err_msg or "not found" in err_msg.lower():
            return SettingsTestResult(success=False, message=f"Base URL 或模型名称不正确")
        return SettingsTestResult(success=False, message=f"连接失败: {type(exc).__name__}")


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup/shutdown."""
    setup_logging(settings.LOG_LEVEL)
    logger.info("DeepResearch-Agent starting up (log_level=%s)", settings.LOG_LEVEL)
    logger.info("Redis URL: %s", settings.REDIS_URL)
    logger.info("Chroma DB path: %s", settings.CHROMA_DB_PATH)
    logger.info("RAG index path: %s", settings.RAG_INDEX_PATH)
    logger.info("RAG vector backend: %s", settings.RAG_VECTOR_BACKEND)
    logger.info("Milvus URI: %s", settings.MILVUS_URI)
    logger.info("Workflow engine: %s", settings.WORKFLOW_ENGINE)
    logger.info("Database URL: %s", settings.DATABASE_URL)

    # Initialise database
    try:
        await init_db()
        logger.info("Database initialised successfully")
    except Exception as exc:
        logger.warning("Database init failed (non-fatal): %s", exc)

    # Seed built-in skills on first run
    try:
        seeded = await seed_builtin_skills()
        if seeded:
            logger.info("Seeded %d built-in skills", seeded)
    except Exception as exc:
        logger.warning("Skill seeding failed (non-fatal): %s", exc)

    # Recover interrupted tasks
    try:
        await _task_manager.recover_interrupted_tasks()
    except Exception as exc:
        logger.warning("Task recovery failed (non-fatal): %s", exc)

    # Rebuild in-memory BM25 index from persisted vector store so hybrid
    # retrieval works after restart without re-ingesting documents.
    try:
        from app.rag.service import get_rag_retriever

        retriever = get_rag_retriever()
        rebuild = getattr(retriever, "rebuild_bm25_from_store", None)
        if rebuild is not None:
            await rebuild()
    except Exception as exc:
        logger.warning("BM25 index rebuild failed (non-fatal): %s", exc)

    yield

    logger.info("DeepResearch-Agent shutting down")
    await close_db()


app = FastAPI(
    title="DeepResearch-Agent",
    description="Multi-agent collaborative research analysis system",
    version="0.1.0",
    lifespan=lifespan,
)

# Register middleware (CORS, request logging, error handling)
register_middleware(app)

# Register auth router
from app.auth.router import router as auth_router
app.include_router(auth_router)

import os

# Mount static files (fallback UI — always available)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# React built frontend (from Vite: app/web/dist/)
_react_dist = os.path.join("app", "web", "dist")
_react_index = os.path.join(_react_dist, "index.html")
_has_react = os.path.exists(_react_index)

if _has_react and os.path.isdir(os.path.join(_react_dist, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(_react_dist, "assets")), name="react-assets")


def _serve_react() -> HTMLResponse:
    """Read and return the React index.html."""
    with open(_react_index, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/")
async def serve_ui():
    """Serve the React-built UI if available, else the self-contained static UI."""
    if _has_react:
        return _serve_react()
    static_path = os.path.join("app", "static", "index.html")
    if os.path.exists(static_path):
        with open(static_path, encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>DeepResearch-Agent</h1><p>UI not found.</p>")


# ---------------------------------------------------------------------------
# Request / Response schemas
# ---------------------------------------------------------------------------


class ResearchStartRequest(BaseModel):
    """Request body for starting a research task."""

    task: str = Field(..., min_length=1, max_length=5000, description="Research topic")
    max_iterations: int = Field(default=3, ge=1, le=10)
    format: str = Field(default="markdown", pattern=r"^(markdown|pdf|both)$")
    use_rag: bool = Field(default=False, description="Whether to use RAG knowledge base")
    engine: Optional[Literal["langgraph", "harness"]] = Field(
        default=None,
        description="Workflow engine: langgraph or harness",
    )


class PrepareTaskRequest(BaseModel):
    """Body for creating a task WITHOUT starting the workflow."""

    task: str = Field(..., min_length=1, max_length=5000, description="Research topic")


class StartPreparedRequest(BaseModel):
    """Body for starting an already-prepared (pre-created) task."""

    max_iterations: int = Field(default=3, ge=1, le=10)
    format: str = Field(default="markdown", pattern=r"^(markdown|pdf|both)$")
    use_rag: bool = Field(default=False)
    engine: Optional[Literal["langgraph", "harness"]] = Field(
        default=None,
        description="Workflow engine: langgraph or harness",
    )


class HistoryResponse(BaseModel):
    """Response containing list of past tasks."""

    tasks: List[Dict[str, Any]] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    total_pages: int = 1


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(status="ok", version="0.1.0")


@app.post("/api/research")
async def start_research(
    request: ResearchStartRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
) -> ResearchResponse:
    """Start a research task.

    Creates the task, launches background research, and returns immediately
    with the task_id for status polling / SSE streaming.
    """
    profile = await get_effective_profile(current_user)
    task_id = await _task_manager.start_research(
        task_text=request.task,
        max_iterations=request.max_iterations,
        fmt=request.format,
        use_rag=request.use_rag,
        profile_id=profile["id"],
        engine=request.engine,
    )

    return ResearchResponse(
        task_id=task_id,
        status="pending",
        started_at=datetime.now(),
    )


@app.post("/api/research/prepare", response_model=ResearchResponse)
async def prepare_research_task(
    request: PrepareTaskRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
) -> ResearchResponse:
    """Create a research task and provision its workspace WITHOUT starting."""
    task_id = _task_manager.create_task(request.task)

    from app.config import settings
    from app.services.workspace import WorkspaceManager

    task_info = _task_manager.get_task(task_id)
    ws = WorkspaceManager(root_dir=settings.WORKSPACE_ROOT)
    task_info.workspace_dir = await ws.ensure_workspace(task_id)
    task_info.workspace_files = [f["name"] for f in ws.list_files(task_id)]
    return ResearchResponse(task_id=task_id, status="pending")


@app.post("/api/research/{task_id}/start", response_model=ResearchResponse)
async def start_prepared_research(
    task_id: str,
    request: StartPreparedRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
) -> ResearchResponse:
    task_info = _task_manager.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    if task_info.status in ("running", "completed", "failed"):
        raise HTTPException(status_code=409, detail="任务已启动")

    profile = await get_effective_profile(current_user)
    try:
        await _task_manager.start_prepared_task(
            task_id,
            max_iterations=request.max_iterations,
            fmt=request.format,
            use_rag=request.use_rag,
            profile_id=profile["id"],
            engine=request.engine,
        )
    except KeyError:
        # Task vanished between the guard above and the service call (e.g. a
        # concurrent delete_task). Surface a clean 404, not a 500.
        raise HTTPException(status_code=404, detail="Task not found")
    except ValueError:
        # Atomic guard inside start_prepared_task caught a concurrent
        # double-start; the pre-check above was stale.
        raise HTTPException(status_code=409, detail="任务已启动")
    return ResearchResponse(task_id=task_id, status="pending")


@app.post("/api/research/{task_id}/upload")
async def upload_research_file(
    task_id: str,
    file: UploadFile = File(...),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Upload a reference file into a research task's workspace."""
    task_info = _task_manager.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")

    from app.services.workspace import FileCountLimitExceededError, WorkspaceManager

    allowed = [e.strip() for e in settings.UPLOAD_ALLOWED_EXTS.split(",")]
    content = await file.read()
    if len(content) > settings.UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    if file.filename is None or not file.filename.strip():
        raise HTTPException(status_code=400, detail="Empty filename")

    ws = WorkspaceManager(root_dir=settings.WORKSPACE_ROOT)
    try:
        meta = await ws.save_upload(
            task_id,
            filename=file.filename,
            content=content,
            max_bytes=settings.UPLOAD_MAX_BYTES,
            max_files=settings.UPLOAD_MAX_FILES,
            allowed_exts=tuple(allowed),
        )
    except FileCountLimitExceededError as exc:
        # The per-task file-count cap is a resource limit → 413.
        raise HTTPException(status_code=413, detail=str(exc))
    except ValueError as exc:
        # Everything else is a client error → 400.
        raise HTTPException(status_code=400, detail=str(exc))

    # Sync task_info file listing
    task_info.workspace_files = [f["name"] for f in ws.list_files(task_id)]
    return {"name": meta["name"], "size_bytes": meta["size_bytes"]}


@app.get("/api/research/{task_id}/workspace")
async def list_workspace_files(
    task_id: str,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """List files in a research task's workspace."""
    task_info = _task_manager.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")

    from app.services.workspace import WorkspaceManager

    ws = WorkspaceManager(root_dir=settings.WORKSPACE_ROOT)
    files = ws.list_files(task_id)
    task_info.workspace_files = [f["name"] for f in files]
    return {"task_id": task_id, "files": files}


@app.get("/api/research/{task_id}/stream")
async def stream_research_events(request: Request, task_id: str):
    """SSE endpoint: stream agent events as they happen."""
    task_info = _task_manager.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")

    event_queue: asyncio.Queue = asyncio.Queue(maxsize=500)
    _task_manager.register_sse_queue(task_id, event_queue)

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            yield f"event: connected\ndata: {json.dumps({'status': 'connected'})}\n\n"

            while True:
                if await request.is_disconnected():
                    break

                try:
                    event_data = await asyncio.wait_for(event_queue.get(), timeout=10.0)
                    event_type = event_data.pop("type", "message")
                    data_json = json.dumps(event_data)

                    if event_type in ("completed", "error"):
                        yield f"event: {event_type}\ndata: {data_json}\n\n"
                        break
                    else:
                        yield f"event: {event_type}\ndata: {data_json}\n\n"

                except asyncio.TimeoutError:
                    yield f": keepalive\n\n"

        finally:
            _task_manager.unregister_sse_queue(task_id, event_queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/research/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str) -> TaskStatusResponse:
    """Get the current status of a research task."""
    task_info = _task_manager.get_task(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")

    return TaskStatusResponse(
        task_id=task_info.task_id,
        status=task_info.status,
        current_step=len(task_info.events),
        total_steps=100,
        progress=1.0 if task_info.status == "completed" else 0.5 if task_info.status == "running" else 0.0,
        errors=task_info.errors,
    )


@app.get("/api/reports/{task_id}")
async def download_report(
    task_id: str,
    format: str = Query("markdown", pattern=r"^(markdown|pdf)$"),
):
    """Download a report in markdown or PDF format."""
    task_info = _task_manager.get_task(task_id)

    # If in-memory task exists and is completed, serve from memory
    if task_info and task_info.status == "completed":
        if format == "pdf":
            try:
                report_content = task_info.final_report
                pdf_path = os.path.join("data", "reports", f"{task_id}.pdf")
                if not os.path.exists(pdf_path):
                    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
                    await generate_pdf(report_content, pdf_path)
                return FileResponse(
                    pdf_path,
                    media_type="application/pdf",
                    filename=f"research-report-{task_id}.pdf",
                )
            except Exception as exc:
                logger.exception("PDF generation failed")
                raise HTTPException(status_code=500, detail=f"PDF generation failed: {exc}")
        else:
            return Response(
                content=task_info.final_report,
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="research-report-{task_id}.md"',
                },
            )

    # Fall back to persisted report from disk
    if format == "pdf":
        pdf_path = await _report_service.get_report(task_id, fmt="pdf")
        if pdf_path:
            return FileResponse(
                pdf_path,
                media_type="application/pdf",
                filename=f"research-report-{task_id}.pdf",
            )
        md_content = await _report_service.get_report(task_id, fmt="markdown")
        if md_content:
            pdf_out = os.path.join("data", "reports", f"{task_id}.pdf")
            if not os.path.exists(pdf_out):
                os.makedirs(os.path.dirname(pdf_out), exist_ok=True)
                await generate_pdf(md_content, pdf_out)
            return FileResponse(
                pdf_out,
                media_type="application/pdf",
                filename=f"research-report-{task_id}.pdf",
            )
    else:
        content = await _report_service.get_report(task_id, fmt="markdown")
        if content:
            return Response(
                content=content,
                media_type="text/markdown",
                headers={
                    "Content-Disposition": f'attachment; filename="research-report-{task_id}.md"',
                },
            )

    if task_info and task_info.status != "completed":
        raise HTTPException(status_code=400, detail="Task not yet completed")

    raise HTTPException(status_code=404, detail="Report not found")


@app.post("/api/reports/batch-delete")
async def batch_delete_reports(request: Request):
    """Delete multiple research reports at once."""
    body = await request.json()
    ids = body if isinstance(body, list) else body.get("ids", [])
    import shutil
    deleted = []
    for task_id in ids:
        _task_manager.delete_task(task_id)
        report_dir = os.path.join("data", "reports", task_id)
        if os.path.isdir(report_dir):
            shutil.rmtree(report_dir)
            deleted.append(task_id)
    return {"status": "ok", "deleted": deleted, "count": len(deleted)}


@app.get("/api/history")
async def list_history(page: int = Query(1, ge=1), per_page: int = Query(100, ge=1, le=500)):
    """List historical research tasks with pagination."""
    tasks = _task_manager.list_tasks()

    # Also include persisted reports from disk
    try:
        persisted = _report_service.list_reports(limit=200)
        existing_ids = {t["task_id"] for t in tasks}
        for r in persisted:
            tid = r.get("task_id") or r.get("report_id", "")
            if tid and tid not in existing_ids:
                task_name = r.get("task_display", tid)
                tasks.append({
                    "task_id": tid,
                    "task": task_name,
                    "status": "completed",
                    "created_at": r.get("created_at", ""),
                    "completed_at": r.get("created_at", ""),
                    "summary": "",
                })
    except Exception:
        pass

    tasks.sort(key=lambda t: t.get("created_at", ""), reverse=True)

    total = len(tasks)
    total_pages = max(1, math.ceil(total / per_page))
    start = (page - 1) * per_page
    paged = tasks[start:start + per_page]

    return {"tasks": paged, "total": total, "page": page, "total_pages": total_pages}


@app.post("/api/knowledge/ingest")
async def knowledge_ingest(request: Request):
    """Ingest a document into the RAG knowledge base."""
    body = await request.json()
    content = body.get("content", "")
    source = body.get("source", "unknown")
    doc_type = body.get("doc_type", "text")

    if not content or not content.strip():
        raise HTTPException(status_code=400, detail="Content is empty")

    from app.rag.service import get_rag_retriever

    retriever = get_rag_retriever()
    try:
        chunk_ids = await retriever.ingest_document(content=content, source=source, doc_type=doc_type)
        return {"status": "ok", "count": len(chunk_ids), "chunk_ids": chunk_ids}
    except Exception as e:
        logger.exception("Knowledge ingest failed")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/knowledge/search")
async def knowledge_search(
    q: str = Query(..., min_length=1),
    k: int = Query(5, ge=1, le=20),
    dedupe_by_source: bool = Query(True, description="按来源文档去重，每个文档只保留最匹配的片段"),
):
    """Search the RAG knowledge base (hybrid when enabled, dense otherwise).

    By default results are grouped by source document so one article appears
    only once (with its best-matching chunk). Pass ``dedupe_by_source=false``
    to get raw chunk-level results.
    """
    from app.rag.service import get_rag_retriever

    retriever = get_rag_retriever()
    # Fetch extra candidates so after dedup we can still fill k distinct sources.
    results = await retriever.retrieve(q, k=max(k * 3, 15))

    if not dedupe_by_source:
        return results[:k]

    grouped: dict[str, dict] = {}
    order: list[str] = []
    for r in results:
        src = (r.get("metadata") or {}).get("source", "") or ""
        if src not in grouped:
            grouped[src] = {**r, "matched_chunks": 1}
            order.append(src)
        else:
            grouped[src]["matched_chunks"] += 1

    deduped = [grouped[src] for src in order if grouped[src].get("text")]
    return deduped[:k]


@app.get("/api/knowledge/list")
async def knowledge_list():
    """List all documents in the knowledge base."""
    from app.rag.service import get_rag_retriever

    retriever = get_rag_retriever()
    docs = await retriever.list_documents()
    return docs


@app.delete("/api/knowledge/docs")
async def knowledge_delete_docs(request: Request):
    """Delete a document from the knowledge base by source name."""
    body = await request.json()
    source = body.get("source", "")
    if not source:
        raise HTTPException(status_code=400, detail="Missing 'source'")
    from app.rag.service import get_rag_retriever

    retriever = get_rag_retriever()
    deleted = await retriever.delete_by_source(source)
    return {"status": "ok", "deleted": deleted, "source": source}


@app.get("/api/settings", response_model=SettingsResponse)
async def get_settings():
    """Get current LLM settings (API key masked)."""
    config = _get_cached_config()
    if config.api_key:
        return SettingsResponse(
            configured=True,
            provider=config.provider,
            api_key=mask_api_key(config.api_key),
            model=config.model,
            base_url=config.base_url,
            embedding_model=config.embedding_model,
            embedding_api_key=mask_api_key(config.embedding_api_key) if config.embedding_api_key else "",
            embedding_base_url=config.embedding_base_url,
            embedding_configured=bool(config.embedding_api_key),
            reranker_enabled=config.reranker_enabled,
            reranker_api_key=mask_api_key(config.reranker_api_key) if config.reranker_api_key else "",
            reranker_base_url=config.reranker_base_url,
            reranker_model=config.reranker_model,
        )
    return SettingsResponse(configured=False)


@app.post("/api/settings", response_model=SettingsTestResult)
async def update_settings(request: SettingsUpdateRequest):
    """Save and test LLM settings."""
    api_key = request.api_key.strip()
    if not api_key:
        return SettingsTestResult(success=False, message="API Key 不能为空")

    existing = load_runtime_config()
    embedding_api_key = (
        request.embedding_api_key.strip()
        if request.embedding_api_key and request.embedding_api_key.strip()
        else (existing.embedding_api_key if existing else "")
    )
    embedding_base_url = (
        request.embedding_base_url.strip()
        if request.embedding_base_url and request.embedding_base_url.strip()
        else (existing.embedding_base_url if existing else "")
    )
    embedding_model = (
        request.embedding_model.strip()
        if request.embedding_model and request.embedding_model.strip()
        else (existing.embedding_model if existing else "text-embedding-v3")
    )
    reranker_enabled = (
        request.reranker_enabled
        if request.reranker_enabled is not None
        else (existing.reranker_enabled if existing else False)
    )
    reranker_api_key = (
        request.reranker_api_key.strip()
        if request.reranker_api_key and request.reranker_api_key.strip()
        else (existing.reranker_api_key if existing else "")
    )
    reranker_base_url = (
        request.reranker_base_url.strip()
        if request.reranker_base_url and request.reranker_base_url.strip()
        else (existing.reranker_base_url if existing else "")
    )
    reranker_model = (
        request.reranker_model.strip()
        if request.reranker_model and request.reranker_model.strip()
        else (existing.reranker_model if existing else "")
    )

    config = RuntimeLLMConfig(
        provider=request.provider,
        api_key=api_key,
        model=request.model.strip(),
        base_url=request.base_url.strip() or DEFAULT_BASE_URLS.get(request.provider, ""),
        embedding_model=embedding_model,
        embedding_api_key=embedding_api_key,
        embedding_base_url=embedding_base_url,
        reranker_enabled=reranker_enabled,
        reranker_api_key=reranker_api_key,
        reranker_base_url=reranker_base_url,
        reranker_model=reranker_model,
    )

    # Test connection before saving
    test_result = await _test_llm_connection(config)
    if not test_result.success:
        return test_result

    # Persist and update cache
    save_runtime_config(config)
    _invalidate_config_cache()
    logger.info(
        "LLM settings saved (provider=%s, model=%s, embedding=%s)",
        config.provider,
        config.model,
        config.embedding_model,
    )
    return test_result


@app.get("/api/skills", response_model=List[SkillResponse])
async def api_list_skills(
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """List all skills with per-profile flags."""
    profile = await get_effective_profile(current_user)
    return await list_skills_for_profile(profile["id"])


@app.post("/api/skills", response_model=SkillResponse)
async def api_create_skill(
    payload: SkillCreate,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Create a private skill owned by the current profile."""
    profile = await get_effective_profile(current_user)
    try:
        return await create_skill({**payload.model_dump(), "owner_id": profile["id"]})
    except (DuplicateSkillNameError, InvalidSkillError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.put("/api/skills/{skill_id}", response_model=SkillResponse)
async def api_update_skill(skill_id: str, payload: SkillUpdate):
    """Update a skill (partial update)."""
    try:
        updated = await update_skill(skill_id, payload.model_dump(exclude_unset=True))
    except (DuplicateSkillNameError, InvalidSkillError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if updated is None:
        raise HTTPException(status_code=404, detail="技能不存在")
    return updated


@app.delete("/api/skills/{skill_id}")
async def api_delete_skill(skill_id: str):
    """Delete a skill."""
    if not await delete_skill(skill_id):
        raise HTTPException(status_code=404, detail="技能不存在")
    return {"deleted": True}


@app.post("/api/skills/match", response_model=SkillMatchResponse)
async def api_match_skills(
    payload: SkillMatchRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Return skills that would match a task for the current profile."""
    profile = await get_effective_profile(current_user)
    from app.services.skill_service import VALID_AGENTS, match_skills

    if payload.agent:
        return SkillMatchResponse(
            skills=await match_skills(
                payload.task, payload.agent, profile_id=profile["id"]
            )
        )

    matches = []
    for agent in VALID_AGENTS:
        matched = await match_skills(
            payload.task, agent, profile_id=profile["id"]
        )
        if matched:
            matches.append(
                {"agent": agent, "skills": matched}
            )
    return SkillMatchResponse(
        matches=matches
    )


@app.put("/api/skills/{skill_id}/pref")
async def api_set_skill_pref(
    skill_id: str,
    payload: SkillPrefRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Enable/disable a global skill for the current profile."""
    profile = await get_effective_profile(current_user)
    if not await set_skill_pref(profile["id"], skill_id, payload.enabled):
        raise HTTPException(status_code=404, detail="技能不存在或不是全局技能")
    return {"enabled": payload.enabled}


@app.get("/api/profile", response_model=ProfileResponse)
async def api_get_profile(
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Get the current profile (default when anonymous)."""
    return await get_effective_profile(current_user)


@app.put("/api/profile", response_model=ProfileResponse)
async def api_update_profile(
    payload: ProfileUpdateRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Update the current profile."""
    profile = await get_effective_profile(current_user)
    updated = await update_user_profile(profile["id"], payload.model_dump(exclude_unset=True))
    if updated is None:
        raise HTTPException(status_code=404, detail="档案不存在")
    return updated


@app.get("/api/evolution/drafts", response_model=List[EvolutionDraftResponse])
async def api_list_drafts(
    status: str = Query(default="pending"),
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """List evolution drafts for the current profile."""
    profile = await get_effective_profile(current_user)
    return await list_drafts(profile["id"], status=status)


@app.post("/api/evolution/drafts/{draft_id}/accept", response_model=SkillResponse)
async def api_accept_draft(
    draft_id: str,
    payload: EvolutionAcceptRequest,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Accept a draft, creating a real skill."""
    profile = await get_effective_profile(current_user)
    edits = payload.edits.model_dump(exclude_unset=True) if payload.edits else None
    try:
        skill = await accept_draft(
            draft_id,
            profile["id"],
            promote_global=payload.promote_global,
            edits=edits,
        )
    except (DuplicateSkillNameError, InvalidSkillError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if skill is None:
        raise HTTPException(status_code=404, detail="草稿不存在或不属于当前档案")
    return skill


@app.post("/api/evolution/drafts/{draft_id}/reject")
async def api_reject_draft(
    draft_id: str,
    current_user: Optional[dict] = Depends(get_optional_user),
):
    """Reject a draft."""
    profile = await get_effective_profile(current_user)
    if not await reject_draft(draft_id, profile["id"]):
        raise HTTPException(status_code=404, detail="草稿不存在或不属于当前档案")
    return {"rejected": True}


# ---------------------------------------------------------------------------
# SPA catch-all — serve React index.html for any non-API path
# so that React Router works on page refresh / direct URL access.
# ---------------------------------------------------------------------------


@app.get("/{full_path:path}")
async def spa_fallback(full_path: str):
    """Catch-all: serve React app for non-API routes."""
    # Only intercept non-API paths
    if full_path.startswith("api/") or full_path.startswith("static/") or full_path.startswith("assets/"):
        raise HTTPException(status_code=404, detail="Not found")
    if _has_react:
        return _serve_react()
    raise HTTPException(status_code=404, detail="Not found")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL,
    )
