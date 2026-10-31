"""FastAPI application providing web endpoints for the autonomous coding agent.

Exposes REST endpoints for health checks and conversational agent turns.
"""
import os
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.api.schemas import ChatRequest, ChatResponse, HealthResponse
from app.config import settings
from app.core.agent import CodingAgent
from app.tools import ToolRegistry
from app.tools.file_search import GlobTool
from app.tools.file_system import ReadFileTool, WriteFileTool
from app.tools.terminal import ShellTool

PROJECT_ROOT = Path(__file__).resolve().parents[3]

app = FastAPI(
    title="Autonomous Coding Agent API",
    version="0.1.0",
    description="Hexagonal Web Adapter for the Autonomous Coding Agent engine",
)

# Enable CORS for the future React frontend (port 3000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_agent() -> CodingAgent:
    """Builds a CodingAgent instance scoped strictly to the target workspace."""
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
    """ Root endpoint to inform user about docs """
    return {"message": "Autonomous Coding Agent API is online. Visit /docs for API documentation."}


@app.post("/api/chat", response_model=ChatResponse, tags=["Agent"])
async def chat(payload: ChatRequest):
    """Executes an agent turn given conversation history."""
    if not payload.workspace:
        raise HTTPException(status_code=400, detail="A workspace must be specified.")

    # Anchor to PROJECT_ROOT and resolve
    raw_path = Path(payload.workspace)
    target_path = (raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path).resolve()

    # Prevent directory escape
    if not str(target_path).startswith(str(PROJECT_ROOT)):
        raise HTTPException(status_code=400, detail="Access outside project directory is forbidden.")

    # Ensure the user's selected folder exists, then update process dir
    target_path.mkdir(parents=True, exist_ok=True)
    settings.WORKSPACE_DIR = str(target_path)
    os.chdir(target_path)

    try:
        agent = get_agent()
        history_dicts = [msg.model_dump() for msg in payload.messages]
        
        # Run agent
        result = agent.run(history_dicts)
        return ChatResponse(response=result or "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e)) from e


@app.get("/api/workspace/files", tags=["Agent"])
async def list_workspace_files(workspace: str = "workspace"):
    """Returns a list of relative file paths in the selected workspace."""
    raw_path = Path(workspace)
    target_path = (raw_path if raw_path.is_absolute() else PROJECT_ROOT / raw_path).resolve()

    if not target_path.exists() or not str(target_path).startswith(str(PROJECT_ROOT)):
        return {"files": []}

    ignored = {".git", ".venv", "__pycache__", "node_modules"}
    file_list = []
    for p in target_path.rglob("*"):
        if p.is_file() and not any(part in ignored for part in p.parts):
            file_list.append(str(p.relative_to(target_path)))

    return {"files": sorted(file_list)}