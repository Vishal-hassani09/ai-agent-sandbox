import os
from typing import Any, Dict, List, Optional
import httpx

DEFAULT_RENDER_BACKEND = "https://ai-agent-sandbox-backend-dgcj.onrender.com"
BASE_URL = (
    os.getenv("AI_CODER_API_URL")
    or os.getenv("API_BASE_URL")
    or DEFAULT_RENDER_BACKEND
).rstrip("/")


class AssistantAPIClient:
    def __init__(self, token: str, base_url: Optional[str] = None):
        self.token = token
        self.base_url = (base_url or BASE_URL).rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "X-Auth-Token": token,
            "Content-Type": "application/json",
        }

    def list_sessions_for_workspace(self, workspace_path: str) -> List[Dict[str, Any]]:
        with httpx.Client(base_url=self.base_url, timeout=15.0) as client:
            res = client.get(
                "/api/sessions",
                params={"workspace_path": workspace_path},
                headers=self._headers,
            )
            res.raise_for_status()
            return res.json()

    def create_session(self, workspace_path: str, title: Optional[str] = None) -> Dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=15.0) as client:
            res = client.post(
                "/api/sessions",
                json={"workspace_path": workspace_path, "title": title or "CLI Session"},
                headers=self._headers,
            )
            res.raise_for_status()
            return res.json()

    def get_session_detail(self, session_id: str) -> Dict[str, Any]:
        with httpx.Client(base_url=self.base_url, timeout=15.0) as client:
            res = client.get(f"/api/sessions/{session_id}", headers=self._headers)
            res.raise_for_status()
            return res.json()

    def send_chat_message(self, session_id: str, content: str) -> str:
        with httpx.Client(base_url=self.base_url, timeout=90.0) as client:
            res = client.post(
                "/api/chat",
                json={"session_id": session_id, "content": content},
                headers=self._headers,
            )
            res.raise_for_status()
            data = res.json()
            return data.get("response", "")