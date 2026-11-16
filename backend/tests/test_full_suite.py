"""Automated test suite covering OTP/CAPTCHA Auth, Device Bridge, Local Tool Executor, and Tool Schemas."""
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from pathlib import Path
from prompt_toolkit.completion import CompleteEvent
from prompt_toolkit.document import Document
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.auth import _reg_flows
from app.api.main import app
from app.api.ws import DaemonConnectionManager, LocalDaemonBridge
from app.cli.tool_executor import LocalToolExecutor
from app.cli.ui import ChatInputCompleter, SAFE_READ_ONLY_TOOLS
from app.db.models import Base
from app.db.session import get_db
from app.tools import get_default_registry


# =====================================================================
# 1. IN-MEMORY DATABASE FIXTURE FOR FASTAPI INTEGRATION TESTS
# =====================================================================

@pytest_asyncio.fixture
async def test_client():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    _reg_flows.clear()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client

    app.dependency_overrides.clear()
    _reg_flows.clear()
    await engine.dispose()


# =====================================================================
# 2. MULTI-STEP OTP, CAPTCHA & RATE LIMITING TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_otp_captcha_and_rate_limit_registration_flow(test_client: AsyncClient):
    email = "newdev@example.com"

    # Attempts 1, 2, 3 -> OTP sent directly without CAPTCHA
    for attempt in range(1, 4):
        res = await test_client.post(
            "/api/auth/generate-otp",
            json={"email": email, "is_captcha_resend": False},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "otp_sent"
        assert data["otp_attempts"] == attempt
        assert data["captcha_id"] is None

    # Attempt 4 -> CAPTCHA required
    res4 = await test_client.post(
        "/api/auth/generate-otp",
        json={"email": email, "is_captcha_resend": False},
    )
    assert res4.status_code == 200
    data4 = res4.json()
    assert data4["status"] == "captcha_required"
    assert data4["captcha_id"]
    assert "<svg" in data4["captcha_svg"]

    # Resend CAPTCHA 5 times (allowed)
    for resend_idx in range(1, 6):
        r_cap = await test_client.post(
            "/api/auth/generate-otp",
            json={"email": email, "is_captcha_resend": True},
        )
        assert r_cap.status_code == 200
        assert r_cap.json()["captcha_resends"] == resend_idx

    # 6th CAPTCHA resend -> 429 Too Many Requests
    r_limit = await test_client.post(
        "/api/auth/generate-otp",
        json={"email": email, "is_captcha_resend": True},
    )
    assert r_limit.status_code == 429

    # Solve current active CAPTCHA -> automatically sends fresh OTP
    flow = _reg_flows[email]
    cid = flow.active_captcha.captcha_id
    answer = flow.active_captcha.answer

    cap_verify = await test_client.post(
        "/api/auth/verify-captcha",
        json={"email": email, "captcha_id": cid, "captcha_answer": answer.lower()},
    )
    assert cap_verify.status_code == 200
    assert cap_verify.json()["status"] == "otp_sent"

    # Attempting /register without valid verification_token must fail (403)
    bad_reg = await test_client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "StrongPassword123",
            "verification_token": "forged-token",
        },
    )
    assert bad_reg.status_code == 403

    # Verify OTP -> receives verification_token -> completes registration
    otp_code = _reg_flows[email].otp_code
    otp_verify = await test_client.post(
        "/api/auth/verify-otp",
        json={"email": email, "otp": otp_code},
    )
    assert otp_verify.status_code == 200
    v_token = otp_verify.json()["verification_token"]

    good_reg = await test_client.post(
        "/api/auth/register",
        json={
            "email": email,
            "password": "StrongPassword123",
            "verification_token": v_token,
        },
    )
    assert good_reg.status_code == 200
    reg_data = good_reg.json()
    assert reg_data["email"] == email
    assert reg_data["access_token"]


# =====================================================================
# 3. DEVICE BRIDGE PAIRING (bridge_id -> claim_bridge) TESTS
# =====================================================================

class _DummyWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_json(self, payload):
        self.sent.append(payload)

    async def close(self, code=1000):
        self.closed = True


@pytest.mark.asyncio
async def test_device_bridge_claim_and_idempotency():
    mgr = DaemonConnectionManager()
    ws = _DummyWebSocket()
    bridge = LocalDaemonBridge(websocket=ws, user_email="", cwd="/tmp/project")

    await mgr.register_unclaimed("bridge-123", bridge)
    assert mgr.get("dev@example.com") is None

    # Claim bridge for authenticated user
    claimed = await mgr.claim_bridge("bridge-123", "dev@example.com")
    assert claimed is bridge
    assert mgr.get("dev@example.com") is bridge
    assert any(msg.get("type") == "bridge_claimed" for msg in ws.sent)

    # Idempotent repeat claim returns the already-linked bridge
    claimed_again = await mgr.claim_bridge("bridge-123", "dev@example.com")
    assert claimed_again is bridge


# =====================================================================
# 4. BACKEND TOOL REGISTRY & SCHEMA TESTS
# =====================================================================

def test_default_tool_registry_and_relaxed_schemas():
    registry = get_default_registry()
    schemas = registry.get_schemas()
    schemas_by_name = {s["function"]["name"]: s["function"] for s in schemas}

    expected = {
        "read_file",
        "write_file",
        "edit_file",
        "list_files",
        "execute_command",
        "glob_files",
        "ask_user",
    }
    assert expected.issubset(schemas_by_name.keys())

    for tool_name in ("read_file", "write_file", "edit_file", "list_files", "execute_command"):
        required_props = schemas_by_name[tool_name]["parameters"].get("required", [])
        assert required_props == []


# =====================================================================
# 5. CLI LOCAL TOOL EXECUTOR & COMPLETER TESTS
# =====================================================================

@pytest.mark.asyncio
async def test_cli_tool_executor_write_read_edit_and_sandbox(tmp_path: Path):
    executor = LocalToolExecutor(str(tmp_path))

    write_res = await executor.execute(
        "write_file",
        {"filename": "calc.py", "content": "def add(a, b):\n    return a - b\n"},
    )
    assert "Successfully wrote" in write_res

    read_res = await executor.execute("read_file", {"path": "calc.py"})
    assert "return a - b" in read_res

    edit_res = await executor.execute(
        "edit_file",
        {"path": "calc.py", "old_text": "return a - b", "new_text": "return a + b"},
    )
    assert "Successfully applied edit" in edit_res
    assert "return a + b" in (tmp_path / "calc.py").read_text(encoding="utf-8")

    # Path traversal must be blocked
    with pytest.raises(PermissionError):
        await executor.execute("read_file", {"path": "../secret.txt"})


@pytest.mark.asyncio
async def test_cli_tool_executor_list_glob_and_shell(tmp_path: Path):
    (tmp_path / "app.py").write_text("print(1)", encoding="utf-8")
    (tmp_path / "notes.md").write_text("# Notes", encoding="utf-8")

    executor = LocalToolExecutor(str(tmp_path))
    assert "app.py" in await executor.execute("list_files", {})
    assert "app.py" in await executor.execute("glob_files", {"pattern": "*.py"})
    assert "notes.md" not in await executor.execute("glob_files", {"pattern": "*.py"})

    shell_out = await executor.execute("execute_command", {"command": "echo BRIDGE_OK"})
    assert "BRIDGE_OK" in shell_out


def test_completers_and_read_only_safety(tmp_path: Path):
    (tmp_path / "AGENTS.md").write_text("# Memory", encoding="utf-8")
    completer = ChatInputCompleter(str(tmp_path))

    slash_comps = list(completer.get_completions(Document(text="/co", cursor_position=3), CompleteEvent()))
    assert any(c.text == "/compact" for c in slash_comps)

    file_comps = list(completer.get_completions(Document(text="Read @AG", cursor_position=8), CompleteEvent()))
    assert any(c.text == "AGENTS.md" for c in file_comps)

    assert "readfile" in SAFE_READ_ONLY_TOOLS
    assert "writefile" not in SAFE_READ_ONLY_TOOLS
    assert "executecommand" not in SAFE_READ_ONLY_TOOLS