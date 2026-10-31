"""Integration and contract tests for the API endpoints."""

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from app.api.main import app

client = TestClient(app)


def test_health_check():
    """Verify health endpoint returns status 200 and expected payload."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_list_workspaces():
    """Verify workspace listing returns candidate directories without internal folders."""
    response = client.get("/api/workspaces")
    assert response.status_code == 200
    data = response.json()
    assert "workspaces" in data
    assert isinstance(data["workspaces"], list)
    assert "backend" not in data["workspaces"]
    assert "frontend" not in data["workspaces"]


def test_list_workspace_files():
    """Verify files listing returns a list of files for the default workspace."""
    response = client.get("/api/workspace/files?workspace=workspace")
    assert response.status_code == 200
    data = response.json()
    assert "files" in data
    assert isinstance(data["files"], list)


def test_list_workspace_files_invalid_path():
    """Verify non-existent or traversal paths safely return an empty file list."""
    response = client.get("/api/workspace/files?workspace=../../nonexistent")
    assert response.status_code == 200
    assert response.json() == {"files": []}


def test_chat_missing_workspace():
    """Verify empty workspace payload triggers a 400 Bad Request."""
    response = client.post(
        "/api/chat",
        json={"workspace": "", "messages": [{"role": "user", "content": "hello"}]},
    )
    assert response.status_code == 400
    assert "A workspace must be specified" in response.json()["detail"]


def test_chat_path_traversal_prevention():
    """Verify path traversal payloads escaping project root are blocked."""
    response = client.post(
        "/api/chat",
        json={
            "workspace": "../../../etc",
            "messages": [{"role": "user", "content": "read passwd"}],
        },
    )
    assert response.status_code == 400
    assert "Access outside project directory is forbidden" in response.json()["detail"]


@patch("app.api.main.get_agent")
def test_chat_success(mock_get_agent):
    """Verify successful agent turn execution with mocked agent runner."""
    mock_agent_instance = MagicMock()
    mock_agent_instance.run.return_value = "Mocked agent response"
    mock_get_agent.return_value = mock_agent_instance

    response = client.post(
        "/api/chat",
        json={
            "workspace": "workspace",
            "messages": [{"role": "user", "content": "list files"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["response"] == "Mocked agent response"
    mock_agent_instance.run.assert_called_once()
