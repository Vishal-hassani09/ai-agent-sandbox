"""FastAPI application providing web endpoints for the autonomous coding agent."""
import asyncio
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import router as auth_router
from app.api.deps import get_current_user
from app.api.schemas import ChatRequest, ChatResponse, HealthResponse
from app.api.sessions import router as sessions_router
from app.api.ws import daemon_manager, router as ws_router
from app.config import settings
from app.core.agent import CodingAgent
from app.db.models import ChatMessage, ChatSession, User
from app.db.session import get_db
from app.tools import ToolRegistry
from app.tools.file_search import GlobTool
from app.tools.file_system import ReadFileTool, WriteFileTool
from app.tools.terminal import ShellTool

DEFAULT_WORKSPACE = Path(__file__).resolve().parents[3] / "workspace"
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_DIR", str(DEFAULT_WORKSPACE))).resolve()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

UUID_PATH_RE = re.compile(r"/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Autonomous Coding Agent API",
    version="0.1.0",
    description="Hexagonal Web Adapter for the Autonomous Coding Agent engine",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(SlowAPIMiddleware)

app.include_router(auth_router)
app.include_router(ws_router, prefix="/api")
app.include_router(sessions_router)

ALLOWED_ORIGINS = [
    "https://ai-agent-sandbox-frontend.onrender.com",
    "http://localhost:5173",
    "http://localhost:3000",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_origin_regex=r"https://.*\.onrender\.com",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_agent_for_workspace(workspace_dir: str) -> CodingAgent:
    """Builds a CodingAgent instance with the tool registry scoped to the target workspace."""
    settings.WORKSPACE_DIR = workspace_dir
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(GlobTool())
    registry.register(ShellTool())
    return CodingAgent(registry)


@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint for container checks and uptime monitoring."""
    return HealthResponse()


@app.get("/")
async def root():
    """Root endpoint informing callers about API docs."""
    return {
        "message": "Autonomous Coding Agent API is online. Visit /docs for API documentation."
    }


@app.get("/api/daemon/status", tags=["Device Bridge"])
async def get_daemon_status(current_user: User = Depends(get_current_user)):
    """Checks whether the user's local `ai-coder ui` device bridge is connected."""
    bridge = daemon_manager.get(current_user.email)
    return {
        "connected": bridge is not None,
        "cwd": bridge.cwd if bridge else "",
    }


@app.post("/api/daemon/claim", tags=["Device Bridge"])
async def claim_device_bridge(
    bridge_id: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    """Links an unclaimed local `ai-coder ui` bridge to the user who just logged in on the Web UI."""
    bridge = await daemon_manager.claim_bridge(bridge_id, current_user.email)
    return {
        "connected": bridge is not None,
        "cwd": bridge.cwd if bridge else "",
    }


@app.get("/api/fs/browse", tags=["Device Bridge"])
async def browse_device_folders(
    path: str = Query(default=""),
    current_user: User = Depends(get_current_user),
):
    """Browses directories on the user's connected local device (or local server fallback)."""
    bridge = daemon_manager.get(current_user.email)
    if bridge is not None:
        try:
            return await bridge.call_rpc("browse_folders", {"path": path}, timeout=10.0)
        except asyncio.TimeoutError:
            pass

    current = Path(path).expanduser().resolve() if path.strip() else Path.cwd().resolve()
    if not current.exists() or not current.is_dir():
        current = Path.home().resolve()

    folders = []
    try:
        for entry in sorted(current.iterdir(), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith("."):
                folders.append({"name": entry.name, "path": str(entry.resolve())})
    except PermissionError:
        pass

    parent = str(current.parent) if current.parent != current else None
    return {
        "current_path": str(current),
        "parent_path": parent,
        "folders": folders,
    }


@app.get("/api/workspaces", tags=["Agent"])
async def list_clean_workspaces(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns clean project workspace paths (filtering out internal UUID sandbox directories)."""
    bridge = daemon_manager.get(current_user.email)
    clean_list = []
    if bridge and bridge.cwd:
        clean_list.append(bridge.cwd)

    query = (
        select(ChatSession.workspace_path)
        .where(ChatSession.user_id == current_user.id, ChatSession.workspace_path.isnot(None))
        .distinct()
    )
    res = await db.execute(query)
    for (wp,) in res.fetchall():
        if wp and not UUID_PATH_RE.search(wp) and wp not in clean_list:
            clean_list.append(wp)

    if not clean_list:
        clean_list.append("workspace")
    return {"workspaces": clean_list}


@app.get("/api/workspace/files", tags=["Agent"])
async def list_workspace_files(
    workspace: Optional[str] = Query(default=None),
    session_id: Optional[str] = Query(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Lists files inside the selected workspace from the user's connected local device."""
    target_ws = (workspace or "").strip()

    if not target_ws and session_id:
        query = select(ChatSession).where(
            ChatSession.id == session_id,
            ChatSession.user_id == current_user.id,
        )
        result = await db.execute(query)
        session = result.scalars().first()
        if session and session.workspace_path:
            target_ws = session.workspace_path

    bridge = daemon_manager.get(current_user.email)
    if bridge is not None:
        ws_to_scan = target_ws or bridge.cwd
        try:
            rpc_res = await bridge.call_rpc(
                "list_workspace_files",
                {"workspace_path": ws_to_scan},
                timeout=10.0,
            )
            return {"workspace": ws_to_scan, "files": rpc_res.get("files", [])}
        except Exception:
            pass

    if not target_ws:
        return {"files": []}

    p = Path(target_ws).expanduser()
    target_path = p.resolve() if p.is_absolute() else (WORKSPACE_ROOT / p).resolve()
    if not target_path.exists() or not target_path.is_dir():
        return {"files": []}

    ignored = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache"}
    file_list = []
    for root, dirs, files in os.walk(target_path):
        dirs[:] = [d for d in dirs if d not in ignored]
        for fname in files:
            rel = os.path.relpath(os.path.join(root, fname), target_path).replace("\\", "/")
            file_list.append(rel)
            if len(file_list) >= 500:
                break
        if len(file_list) >= 500:
            break

    return {"workspace": str(target_path), "files": sorted(file_list)}


@app.get("/api/workspace/file", tags=["Agent"])
async def read_workspace_file_content(
    workspace: str = Query(default=""),
    path: str = Query(...),
    current_user: User = Depends(get_current_user),
):
    """Fetches file contents from the user's connected local device (or local server fallback)."""
    target_ws = workspace.strip()
    bridge = daemon_manager.get(current_user.email)
    if bridge is not None:
        ws_to_scan = target_ws or bridge.cwd
        try:
            rpc_res = await bridge.call_rpc(
                "read_workspace_file",
                {"workspace_path": ws_to_scan, "path": path},
                timeout=10.0,
            )
            return rpc_res
        except Exception:
            pass

    p = Path(target_ws).expanduser() if target_ws else WORKSPACE_ROOT
    root = p.resolve() if p.is_absolute() else (WORKSPACE_ROOT / p).resolve()
    target_file = (root / path).resolve()
    if not str(target_file).startswith(str(root)) or not target_file.is_file():
        return {"path": path, "content": "", "error": "File not found"}
    return {
        "path": path,
        "content": target_file.read_text(encoding="utf-8", errors="replace"),
    }


@app.post("/api/chat", response_model=ChatResponse, tags=["Agent"])
@limiter.limit("10/minute")
async def chat(
    request: Request,
    payload: ChatRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Executes a synchronous agent turn against a persistent session and workspace."""
    _ = request
    query = (
        select(ChatSession)
        .where(ChatSession.id == payload.session_id, ChatSession.user_id == current_user.id)
        .options(selectinload(ChatSession.messages))
    )
    result = await db.execute(query)
    session = result.scalars().first()

    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    target_workspace = Path(session.workspace_path or settings.WORKSPACE_DIR).resolve()
    target_workspace.mkdir(parents=True, exist_ok=True)

    user_msg = ChatMessage(session_id=session.id, role="user", content=payload.content)
    db.add(user_msg)
    await db.commit()

    history = [{"role": m.role, "content": m.content} for m in session.messages]
    history.append({"role": "user", "content": payload.content})

    try:
        agent = get_agent_for_workspace(str(target_workspace))
        response_text = agent.run(history)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent execution failed: {str(e)}") from e

    assistant_msg = ChatMessage(session_id=session.id, role="assistant", content=response_text or "")
    db.add(assistant_msg)
    await db.commit()

    return ChatResponse(session_id=session.id, response=response_text or "")