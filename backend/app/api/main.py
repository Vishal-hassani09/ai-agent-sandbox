"""FastAPI application providing web endpoints for the autonomous coding agent.

Exposes REST endpoints for health checks and conversational agent turns.
"""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.schemas import ChatRequest, ChatResponse, HealthResponse
from app.config import settings
from app.core.agent import CodingAgent
from app.tools import ToolRegistry
from app.tools.file_search import GlobTool
from app.tools.file_system import ReadFileTool, WriteFileTool
from app.tools.terminal import ShellTool

# Determine designated execution root (/app/workspace in Docker, or root/workspace locally)
DEFAULT_WORKSPACE = Path(__file__).resolve().parents[3] / "workspace"
WORKSPACE_ROOT = Path(os.getenv("WORKSPACE_DIR", str(DEFAULT_WORKSPACE))).resolve()
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

# 1. Rate Limiter (Restricts requests per remote IP)
limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title="Autonomous Coding Agent API",
    version="0.1.0",
    description="Hexagonal Web Adapter for the Autonomous Coding Agent engine",
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mount SlowAPIMiddleware so incoming request states are properly intercepted
app.add_middleware(SlowAPIMiddleware)

# 2. CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def resolve_safe_workspace(workspace_name: str) -> Path:
    """Resolves workspace paths and forbids directory escapes outside WORKSPACE_ROOT."""
    cleaned = workspace_name.strip().lstrip("/\\")
    target_path = (WORKSPACE_ROOT / cleaned).resolve()

    # Match exact contract required by test_chat_path_traversal_prevention
    if target_path != WORKSPACE_ROOT and not target_path.is_relative_to(WORKSPACE_ROOT):
        raise HTTPException(
            status_code=400,
            detail="Access outside project directory is forbidden.",
        )
    return target_path


def get_agent() -> CodingAgent:
    """Builds a CodingAgent instance with the default tool registry."""
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(GlobTool())
    registry.register(ShellTool())
    return CodingAgent(registry)


@app.get("/api/health", response_model=HealthResponse, tags=["System"])
async def health_check():
    """Health check endpoint for Docker container checks and uptime monitoring."""
    return HealthResponse()


@app.get("/")
async def root():
    """Root endpoint to inform user about docs."""
    return {
        "message": "Autonomous Coding Agent API is online. Visit /docs for API documentation."
    }


@app.post("/api/chat", response_model=ChatResponse, tags=["Agent"])
@limiter.limit("10/minute")
async def chat(request: Request, payload: ChatRequest):
    """Executes an agent turn given conversation history with rate limiting."""
    _ = request  # Satisfies pylint W0613 while keeping request active for SlowAPI

    if not payload.workspace:
        raise HTTPException(status_code=400, detail="A workspace must be specified.")

    target_path = resolve_safe_workspace(payload.workspace)
    target_path.mkdir(parents=True, exist_ok=True)

    # Scoping workspace for tools without changing global process directory
    settings.WORKSPACE_DIR = str(target_path)

    try:
        agent = get_agent()
        history_dicts = [msg.model_dump() for msg in payload.messages]

        result = agent.run(history_dicts)
        return ChatResponse(response=result or "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/workspaces", tags=["Agent"])
async def list_workspaces():
    """List available candidate workspace folders under WORKSPACE_ROOT."""
    ignored = {".git", ".venv", "backend", "frontend", "__pycache__", "node_modules"}
    workspaces = [
        p.name
        for p in WORKSPACE_ROOT.iterdir()
        if p.is_dir() and p.name not in ignored and not p.name.startswith(".")
    ]
    if not workspaces:
        workspaces = ["workspace"]
    return {"workspaces": sorted(workspaces)}


@app.get("/api/workspace/files", tags=["Agent"])
async def list_workspace_files(workspace: str = "workspace"):
    """Returns a list of relative file paths in the selected workspace."""
    try:
        target_path = resolve_safe_workspace(workspace)
    except HTTPException:
        # Gracefully return empty file list on path traversal as expected by contract test
        return {"files": []}

    if not target_path.exists():
        return {"files": []}

    ignored = {".git", ".venv", "__pycache__", "node_modules"}
    file_list = []
    for p in target_path.rglob("*"):
        if p.is_file() and not any(part in ignored for part in p.parts):
            file_list.append(str(p.relative_to(target_path)))

    return {"files": sorted(file_list)}