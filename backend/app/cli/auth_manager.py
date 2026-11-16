import json
import os
from pathlib import Path
from typing import Optional
import httpx
from rich.console import Console
from rich.prompt import Prompt

console = Console()
CONFIG_DIR = Path.home() / ".aicoder"
CREDENTIALS_FILE = CONFIG_DIR / "credentials.json"
BASE_URL = os.getenv("API_BASE_URL", "http://127.0.0.1:8000")


def get_stored_token() -> Optional[str]:
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        data = json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
        return data.get("access_token")
    except Exception:
        return None


def save_token(token: str, email: str):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    payload = {"access_token": token, "email": email}
    CREDENTIALS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    # Secure permissions (read/write only by owner)
    try:
        os.chmod(CREDENTIALS_FILE, 0o600)
    except Exception:
        pass


def login_or_register_cli() -> str:
    token = get_stored_token()
    if token:
        # Validate token against health/session check
        try:
            with httpx.Client(base_url=BASE_URL, timeout=5.0) as client:
                res = client.get("/api/sessions/workspaces/all", headers={"Authorization": f"Bearer {token}"})
                if res.status_code == 200:
                    return token
        except Exception:
            pass  # Fall back to interactive prompt if server fails or token expired

    console.print("[bold yellow]● No active session credentials found. Please log in.[/bold yellow]")
    email = Prompt.ask("[cyan]Enter Email[/cyan]")
    password = Prompt.ask("[cyan]Enter Password[/cyan]", password=True)

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as client:
        # Try login
        login_res = client.post("/api/auth/login", json={"email": email, "password": password})
        if login_res.status_code == 200:
            data = login_res.json()
            tok = data["access_token"]
            save_token(tok, email)
            console.print("[bold green]✓ Logged in successfully.[/bold green]")
            return tok

        # If not found, attempt registration
        reg_res = client.post("/api/auth/register", json={"email": email, "password": password})
        if reg_res.status_code == 200:
            data = reg_res.json()
            tok = data["access_token"]
            save_token(tok, email)
            console.print("[bold green]✓ Account created and logged in.[/bold green]")
            return tok

    raise RuntimeError("Authentication failed. Please verify your credentials or server connection.")