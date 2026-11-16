"""Lightweight local device daemon that connects the user's machine to the Render cloud backend."""
import asyncio
import json
import os
import uuid
import webbrowser
from pathlib import Path
from typing import Any, Dict

import websockets

from app.cli.client import BASE_URL
from app.cli.tool_executor import LocalToolExecutor

DEFAULT_WEB_UI_URL = os.getenv(
    "AI_CODER_WEB_URL",
    "https://ai-agent-sandbox-frontend.onrender.com",
).rstrip("/")


def _browse_local_folders(path_str: str) -> Dict[str, Any]:
    """Lists subdirectories on the user's local machine for the Web UI folder picker."""
    current = Path(path_str).expanduser().resolve() if path_str.strip() else Path.cwd().resolve()
    if not current.exists() or not current.is_dir():
        current = Path.home().resolve()

    folders = []
    try:
        for entry in sorted(current.iterdir(), key=lambda e: e.name.lower()):
            if entry.is_dir() and not entry.name.startswith("."):
                folders.append({
                    "name": entry.name,
                    "path": str(entry.resolve()),
                })
    except PermissionError:
        pass

    parent = str(current.parent) if current.parent != current else None
    return {
        "current_path": str(current),
        "parent_path": parent,
        "folders": folders,
    }


def _list_local_workspace_files(workspace_path: str) -> Dict[str, Any]:
    """Scans relative files in the active workspace on the user's local machine."""
    target = Path(workspace_path).expanduser().resolve() if workspace_path.strip() else Path.cwd().resolve()
    if not target.exists() or not target.is_dir():
        return {"workspace": str(target), "files": []}

    ignored = {".git", ".venv", "__pycache__", "node_modules", ".pytest_cache", "dist", "build"}
    collected = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in dirs if d not in ignored]
        for fname in files:
            rel = os.path.relpath(os.path.join(root, fname), target).replace("\\", "/")
            collected.append(rel)
            if len(collected) >= 500:
                break
        if len(collected) >= 500:
            break

    return {"workspace": str(target), "files": sorted(collected)}


def _read_local_workspace_file(workspace_path: str, rel_path: str) -> Dict[str, Any]:
    """Reads a single file inside the active workspace on the user's local machine."""
    root = Path(workspace_path).expanduser().resolve() if workspace_path.strip() else Path.cwd().resolve()
    target_file = (root / rel_path).resolve()
    if not str(target_file).startswith(str(root)):
        return {"path": rel_path, "content": "", "error": "Access denied: path escapes workspace."}
    if not target_file.is_file():
        return {"path": rel_path, "content": "", "error": f"File not found: {rel_path}"}
    try:
        content = target_file.read_text(encoding="utf-8", errors="replace")
        return {"path": rel_path, "content": content}
    except Exception as e:
        return {"path": rel_path, "content": "", "error": str(e)}


async def _daemon_ws_loop(backend_url: str, bridge_id: str, initial_workspace: str):
    """Maintains an outbound WebSocket tunnel to the backend using a one-time bridge_id."""
    ws_base = backend_url.replace("https://", "wss://").replace("http://", "ws://").rstrip("/")
    ws_url = (
        f"{ws_base}/api/ws/daemon"
        f"?bridge_id={bridge_id}"
        f"&cwd={initial_workspace}"
    )

    while True:
        try:
            async with websockets.connect(ws_url, ping_interval=20, ping_timeout=20) as ws:
                print(f"[🟢 Connected] Local device bridge ready on {backend_url}")
                print("  Sign in on the Web UI to link this terminal automatically.\n")
                while True:
                    raw = await ws.recv()
                    data = json.loads(raw)
                    msg_type = data.get("type")
                    req_id = data.get("req_id")

                    if msg_type == "bridge_claimed":
                        print(f"[✓ Linked] Paired with Web UI user: {data.get('email')}")
                        continue

                    if msg_type == "browse_folders":
                        result = _browse_local_folders(data.get("path", ""))
                        await ws.send(json.dumps({"type": "rpc_result", "req_id": req_id, "result": result}))

                    elif msg_type == "list_workspace_files":
                        ws_path = data.get("workspace_path") or initial_workspace
                        result = _list_local_workspace_files(ws_path)
                        await ws.send(json.dumps({"type": "rpc_result", "req_id": req_id, "result": result}))

                    elif msg_type == "read_workspace_file":
                        ws_path = data.get("workspace_path") or initial_workspace
                        rel_path = data.get("path", "")
                        result = _read_local_workspace_file(ws_path, rel_path)
                        await ws.send(json.dumps({"type": "rpc_result", "req_id": req_id, "result": result}))

                    elif msg_type == "tool_call":
                        call_id = data.get("call_id", "")
                        tool_name = data.get("tool", "")
                        tool_args = data.get("args", {})
                        ws_path = data.get("workspace_path") or initial_workspace
                        print(f"  ⚙ Running local tool: {tool_name} in {ws_path}")
                        executor = LocalToolExecutor(ws_path)
                        output = await executor.execute(tool_name, tool_args)
                        await ws.send(json.dumps({
                            "type": "tool_result",
                            "call_id": call_id,
                            "output": output,
                        }))
        except asyncio.CancelledError:
            break
        except Exception as err:
            print(f"[🟡 Reconnecting] Device bridge interrupted ({err}). Retrying in 3s...")
            await asyncio.sleep(3)


def start_ui_daemon(workspace_path: str, open_browser: bool = True, backend_url: str = BASE_URL):
    """Starts the local device bridge with a one-time bridge_id and opens the Web UI."""
    bridge_id = str(uuid.uuid4())
    ui_launch_url = f"{DEFAULT_WEB_UI_URL}/?bridge_id={bridge_id}"

    print("=" * 64)
    print("  AI CODER — Local Device Bridge for Render Web UI")
    print("=" * 64)
    print(f"  📁 Initial Folder : {workspace_path}")
    print(f"  ☁️  Cloud Backend  : {backend_url}")
    print(f"  🌐 Web Studio UI  : {ui_launch_url}")
    print("  Press Ctrl+C in this terminal when you finish using the Web UI.")
    print("=" * 64 + "\n")

    if open_browser:
        try:
            webbrowser.open(ui_launch_url)
        except Exception:
            pass

    try:
        asyncio.run(_daemon_ws_loop(backend_url, bridge_id, workspace_path))
    except KeyboardInterrupt:
        print("\n[AI Coder] Local device bridge stopped.")