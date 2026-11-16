"""WebSocket agent & local device daemon endpoints enabling Render Web UI + local machine tool execution."""
import asyncio
import json
import logging
import uuid
from typing import Any, AsyncGenerator, Dict, List, Optional

import jwt
from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect, status
from groq import AsyncGroq, BadRequestError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import settings
from app.core.security import ALGORITHM, SECRET_KEY
from app.db.models import ChatMessage, ChatSession, User
from app.db.session import get_db
from app.tools import ToolRegistry, get_default_registry

router = APIRouter()
logger = logging.getLogger(__name__)


def _extract_email_from_token(token: str) -> Optional[str]:
    """Extracts user email or subject from a JWT access token."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("email") or payload.get("sub")
    except jwt.PyJWTError:
        return None


class LocalDaemonBridge:
    """Represents a user's connected local CLI machine over /api/ws/daemon."""

    def __init__(self, websocket: WebSocket, user_email: str, cwd: str):
        self.websocket = websocket
        self.user_email = user_email
        self.cwd = cwd
        self.pending_rpc: Dict[str, asyncio.Future] = {}
        self.pending_tools: Dict[str, asyncio.Future] = {}

    async def call_rpc(self, msg_type: str, payload: Dict[str, Any], timeout: float = 15.0) -> Dict[str, Any]:
        req_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.pending_rpc[req_id] = fut
        try:
            await self.websocket.send_json({"type": msg_type, "req_id": req_id, **payload})
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self.pending_rpc.pop(req_id, None)

    async def execute_tool(self, call_id: str, tool_name: str, args: Dict[str, Any], workspace_path: str) -> str:
        loop = asyncio.get_running_loop()
        fut = loop.create_future()
        self.pending_tools[call_id] = fut
        try:
            await self.websocket.send_json({
                "type": "tool_call",
                "call_id": call_id,
                "tool": tool_name,
                "args": args,
                "workspace_path": workspace_path,
            })
            return await asyncio.wait_for(fut, timeout=300.0)
        except asyncio.TimeoutError:
            return f"Error: Local daemon timed out executing '{tool_name}'."
        finally:
            self.pending_tools.pop(call_id, None)

    def resolve_rpc(self, req_id: str, result: Dict[str, Any]) -> None:
        fut = self.pending_rpc.get(req_id)
        if fut and not fut.done():
            fut.set_result(result)

    def resolve_tool(self, call_id: str, output: str) -> None:
        fut = self.pending_tools.get(call_id)
        if fut and not fut.done():
            fut.set_result(output)

    def cancel_all(self) -> None:
        for fut in self.pending_rpc.values():
            if not fut.done():
                fut.set_exception(ConnectionError("Device bridge disconnected"))
        self.pending_rpc.clear()
        for fut in self.pending_tools.values():
            if not fut.done():
                fut.set_result("Error: Local device bridge disconnected during tool execution.")
        self.pending_tools.clear()


class DaemonConnectionManager:
    """Tracks active local CLI device bridges per authenticated user and unclaimed bridge_ids."""

    def __init__(self):
        self._daemons: Dict[str, LocalDaemonBridge] = {}
        self._unclaimed: Dict[str, LocalDaemonBridge] = {}

    async def register(self, user_email: str, bridge: LocalDaemonBridge) -> None:
        old = self._daemons.pop(user_email, None)
        if old and old is not bridge:
            old.cancel_all()
            try:
                await old.websocket.close(code=1000)
            except Exception:
                pass
        self._daemons[user_email] = bridge

    async def register_unclaimed(self, bridge_id: str, bridge: LocalDaemonBridge) -> None:
        old = self._unclaimed.pop(bridge_id, None)
        if old and old is not bridge:
            old.cancel_all()
            try:
                await old.websocket.close(code=1000)
            except Exception:
                pass
        self._unclaimed[bridge_id] = bridge

    async def claim_bridge(self, bridge_id: str, user_email: str) -> Optional[LocalDaemonBridge]:
        bridge = self._unclaimed.pop(bridge_id, None)
        if not bridge:
            return self._daemons.get(user_email)
        bridge.user_email = user_email
        await self.register(user_email, bridge)
        try:
            await bridge.websocket.send_json({"type": "bridge_claimed", "email": user_email})
        except Exception:
            pass
        return bridge

    def unregister(
        self,
        bridge: LocalDaemonBridge,
        user_email: str = "",
        bridge_id: str = "",
    ) -> None:
        if bridge_id and self._unclaimed.get(bridge_id) is bridge:
            self._unclaimed.pop(bridge_id, None)
        target_email = bridge.user_email or user_email
        if target_email and self._daemons.get(target_email) is bridge:
            self._daemons.pop(target_email, None)
        bridge.cancel_all()

    def get(self, user_email: str) -> Optional[LocalDaemonBridge]:
        return self._daemons.get(user_email)


daemon_manager = DaemonConnectionManager()


@router.websocket("/ws/daemon")
async def daemon_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(default=""),
    bridge_id: str = Query(default=""),
    cwd: str = Query(default=""),
):
    """Persistent outbound tunnel from the user's local `ai-coder ui` process."""
    await websocket.accept()
    user_email = ""

    if token:
        extracted = _extract_email_from_token(token)
        if not extracted:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        user_email = extracted
    elif not bridge_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    bridge = LocalDaemonBridge(websocket=websocket, user_email=user_email, cwd=cwd)
    if user_email:
        await daemon_manager.register(user_email, bridge)
        logger.info("Local device daemon connected for %s (cwd=%s)", user_email, cwd)
    else:
        await daemon_manager.register_unclaimed(bridge_id, bridge)
        logger.info("Unclaimed device daemon waiting for Web UI login (bridge_id=%s, cwd=%s)", bridge_id, cwd)

    try:
        while True:
            raw = await websocket.receive_text()
            data = json.loads(raw)
            mtype = data.get("type")
            if mtype == "ping":
                await websocket.send_json({"type": "pong"})
            elif mtype == "rpc_result":
                bridge.resolve_rpc(data.get("req_id", ""), data.get("result", {}))
            elif mtype == "tool_result":
                bridge.resolve_tool(data.get("call_id", ""), data.get("output", ""))
    except WebSocketDisconnect:
        logger.info("Local device daemon disconnected (email=%s, bridge_id=%s)", user_email, bridge_id)
    except Exception:
        logger.exception("Unexpected error in /ws/daemon loop")
    finally:
        daemon_manager.unregister(bridge=bridge, user_email=user_email, bridge_id=bridge_id)


async def generate_smart_title(client: AsyncGroq, user_prompt: str) -> str:
    """Uses a quick zero-shot LLM pass to create a concise 3-5 word title for the session."""
    try:
        resp = await client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Generate a concise 3 to 5 word title summarizing the user prompt. "
                        "Return ONLY the plain title text with no quotation marks, punctuation, or preamble."
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            model=settings.MODEL_NAME,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content or ""
        cleaned = raw.strip().strip('"').strip("'").strip()
        cleaned = cleaned.replace("**", "").replace("*", "").replace("`", "")
        return cleaned[:60] if cleaned else "Fresh CLI Session"
    except Exception as e:
        logger.warning("Failed to auto-generate session title: %s", e)
        words = user_prompt.strip().split()
        return " ".join(words[:5]) if words else "Fresh CLI Session"


async def summarize_history_for_compaction(client: AsyncGroq, messages_to_compact: List[ChatMessage]) -> str:
    """Compresses older conversation turns into a dense, factual engineering summary."""
    transcript_lines = []
    for m in messages_to_compact:
        role_label = m.role.upper()
        snippet = (m.content or "").strip()
        if len(snippet) > 1500:
            snippet = snippet[:1500] + "... [truncated]"
        transcript_lines.append(f"{role_label}: {snippet}")

    transcript_text = "\n".join(transcript_lines)
    try:
        resp = await client.chat.completions.create(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a technical context compactor for a coding assistant. "
                        "Summarize the following conversation history into concise, structured bullet points preserving: "
                        "1) User goals & preferences, 2) Key files created/modified, 3) Decisions & answers given, "
                        "4) Current task state. Keep under 350 words."
                    ),
                },
                {"role": "user", "content": transcript_text},
            ],
            model=settings.MODEL_NAME,
            max_tokens=500,
            temperature=0.2,
        )
        summary = (resp.choices[0].message.content or "").strip()
        return summary or "Previous conversation turns compacted."
    except Exception as e:
        logger.warning("Compaction LLM call failed: %s", e)
        return f"Compacted {len(messages_to_compact)} earlier messages."


class WebSocketToolProxy:
    """Routes tool calls either directly to the CLI client OR via Web UI approval -> Local Device Daemon."""

    def __init__(
        self,
        websocket: WebSocket,
        user_email: str,
        workspace_path: str,
        client_type: str = "cli",
    ):
        self.websocket = websocket
        self.user_email = user_email
        self.workspace_path = workspace_path
        self.client_type = client_type
        self.pending_calls: Dict[str, asyncio.Future] = {}

    async def execute_remote_tool(self, call_id: str, tool_name: str, args: Dict[str, Any]) -> str:
        daemon = daemon_manager.get(self.user_email)
        norm_tool = tool_name.lower().replace("_", "")

        if self.client_type == "web" and daemon is not None and norm_tool != "askuser":
            is_probe = str(call_id).endswith("_probe") or tool_name == "memory_probe"
            if not is_probe:
                approval_raw = await self._send_to_ui_and_wait(
                    call_id=f"approve_{call_id}",
                    msg_type="tool_approval_request",
                    tool_name=tool_name,
                    args=args,
                )
                try:
                    approval_obj = json.loads(approval_raw)
                except Exception:
                    approval_obj = {"approved": False, "message": approval_raw}

                if not approval_obj.get("approved"):
                    return approval_obj.get("message") or f"User declined '{tool_name}'."

            return await daemon.execute_tool(
                call_id=call_id,
                tool_name=tool_name,
                args=args,
                workspace_path=self.workspace_path or daemon.cwd,
            )

        return await self._send_to_ui_and_wait(
            call_id=call_id,
            msg_type="tool_call",
            tool_name=tool_name,
            args=args,
        )

    async def _send_to_ui_and_wait(self, call_id: str, msg_type: str, tool_name: str, args: Dict[str, Any]) -> str:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.pending_calls[call_id] = future

        payload = {
            "type": msg_type,
            "call_id": call_id,
            "tool": tool_name,
            "args": args,
        }
        await self.websocket.send_json(payload)

        try:
            result = await asyncio.wait_for(future, timeout=300.0)
            return result
        except asyncio.TimeoutError:
            return f"Error: Tool execution '{tool_name}' timed out after 300s on client."
        finally:
            self.pending_calls.pop(call_id, None)

    def resolve_call(self, call_id: str, output: str) -> None:
        if call_id in self.pending_calls and not self.pending_calls[call_id].done():
            self.pending_calls[call_id].set_result(output)

    def cancel_all_pending(self) -> None:
        for fut in list(self.pending_calls.values()):
            if not fut.done():
                fut.cancel()
        self.pending_calls.clear()


class RemoteCodingAgent:
    """Inverted agent: prompts and context live on server, tools execute on remote client."""

    def __init__(self, tool_proxy: WebSocketToolProxy, registry: ToolRegistry):
        self.tool_proxy = tool_proxy
        self.registry = registry
        self.client = AsyncGroq(api_key=settings.GROQ_API_KEY)

    def _build_system_prompt(self, workspace_path: str = "", workspace_memory: str = "") -> str:
        workspace_context = f"\nClient active workspace directory: {workspace_path}" if workspace_path else ""
        memory_block = (
            f"\n<workspace_instructions>\n{workspace_memory}\n</workspace_instructions>"
            if workspace_memory
            else ""
        )
        system_prompt = (
            "You are a senior-level coding assistant running with access to the user's local terminal.\n"
            "You have access to tools that execute directly on the user's local workspace via an inverted daemon bridge.\n"
            "Tools available and their exact arguments:\n"
            "- list_files({}): List files in the workspace directory.\n"
            "- read_file({\"filename\": \"...\"}): Read the contents of a file.\n"
            "- write_file({\"filename\": \"...\", \"content\": \"...\"}): Create or overwrite a file.\n"
            "- edit_file({\"path\": \"...\", \"old_text\": \"...\", \"new_text\": \"...\"}): Surgically modify an existing file.\n"
            "- execute_command({\"command\": \"...\"}): Run a shell command in the workspace.\n"
            "- glob_files({\"pattern\": \"...\"}): Find files matching a glob pattern.\n"
            "- ask_user({\"questions\": [...]}): Ask structured clarifying questions with interactive options.\n\n"
            "IMPORTANT RULES:\n"
            "1. Do NOT call any tools on casual greetings, acknowledgments, or general chat (e.g., 'hi', 'hello', 'thanks').\n"
            "2. Always provide all required arguments as valid JSON when calling a tool.\n"
            "3. Once you have written or updated a file (such as AGENTS.md), summarize what you did in plain text and finish your turn instead of calling more tools unnecessarily.\n"
            "4. Always follow repository conventions in <workspace_instructions> if provided."
            f"{workspace_context}"
            f"{memory_block}"
        )
        return f"<system_prompt>{system_prompt}</system_prompt>"

    async def run_turn_stream(
        self,
        history: List[Dict[str, Any]],
        workspace_path: str = "",
        workspace_memory: str = "",
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Runs the agent loop with streaming token outputs and self-healing tool validation recovery."""
        messages: List[Any] = [
            {"role": "system", "content": self._build_system_prompt(workspace_path, workspace_memory)}
        ] + list(history)
        schemas = self.registry.get_schemas()
        iteration = 0

        while iteration <= settings.MAX_ITERATIONS:
            try:
                stream_resp = await self.client.chat.completions.create(
                    messages=messages,
                    tools=schemas if schemas else None,
                    tool_choice="auto" if schemas else None,
                    model=settings.MODEL_NAME,
                    stream=True,
                )
            except BadRequestError as err:
                err_str = str(err)
                if "tool call validation failed" in err_str or "tool_use_failed" in err_str:
                    logger.warning("Groq tool call validation failed on iteration %d, recovering: %s", iteration, err_str)
                    messages.append({
                        "role": "system",
                        "content": (
                            f"Your last tool call failed schema validation ({err_str}). "
                            "If you have already completed the user's task, respond in plain text without calling a tool. "
                            "Otherwise, retry the tool call with the exact required JSON property names."
                        ),
                    })
                    iteration += 1
                    continue
                raise

            accumulated_content = []
            tool_calls_dict: Dict[int, Dict[str, Any]] = {}

            try:
                async for chunk in stream_resp:
                    if not chunk.choices:
                        continue
                    delta = chunk.choices[0].delta

                    if delta.content:
                        accumulated_content.append(delta.content)
                        yield {"type": "token", "delta": delta.content}

                    if delta.tool_calls:
                        for tc_chunk in delta.tool_calls:
                            idx = tc_chunk.index
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {
                                    "id": tc_chunk.id or "",
                                    "type": "function",
                                    "function": {
                                        "name": tc_chunk.function.name if tc_chunk.function else "",
                                        "arguments": tc_chunk.function.arguments if tc_chunk.function else "",
                                    },
                                }
                            else:
                                if tc_chunk.id:
                                    tool_calls_dict[idx]["id"] += tc_chunk.id
                                if tc_chunk.function and tc_chunk.function.name:
                                    tool_calls_dict[idx]["function"]["name"] += tc_chunk.function.name
                                if tc_chunk.function and tc_chunk.function.arguments:
                                    tool_calls_dict[idx]["function"]["arguments"] += tc_chunk.function.arguments
            except BadRequestError as err:
                err_str = str(err)
                if "tool call validation failed" in err_str or "tool_use_failed" in err_str:
                    logger.warning("Groq mid-stream tool validation failed on iteration %d, recovering: %s", iteration, err_str)
                    messages.append({
                        "role": "system",
                        "content": (
                            f"Your last tool call failed schema validation ({err_str}). "
                            "If you have already completed the task, provide your final summary in plain text without calling any tools."
                        ),
                    })
                    iteration += 1
                    continue
                raise

            full_content = "".join(accumulated_content)

            if not tool_calls_dict:
                yield {"type": "turn_complete", "content": full_content}
                return

            tool_calls_list = [tool_calls_dict[i] for i in sorted(tool_calls_dict.keys())]

            messages.append({
                "role": "assistant",
                "content": full_content or None,
                "tool_calls": tool_calls_list,
            })

            for tool_call in tool_calls_list:
                call_id = tool_call["id"]
                tool_name = tool_call["function"]["name"]
                args_raw = tool_call["function"]["arguments"]

                try:
                    tool_args = json.loads(args_raw) if args_raw else {}
                except Exception:
                    tool_args = {}

                output = await self.tool_proxy.execute_remote_tool(
                    call_id=call_id,
                    tool_name=tool_name,
                    args=tool_args,
                )

                messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": tool_name,
                    "content": str(output),
                })

                yield {
                    "type": "tool_executed",
                    "tool": tool_name,
                    "args": tool_args,
                    "output": str(output),
                }

            iteration += 1

        yield {"type": "turn_complete", "content": "Task stopped: maximum reasoning iterations reached."}


@router.websocket("/ws/agent")
async def agent_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(...),
    session_id: str = Query(...),
    client_type: str = Query(default="cli"),
    db: AsyncSession = Depends(get_db),
):
    await websocket.accept()

    # 1. Authenticate token
    user_email = _extract_email_from_token(token)
    if not user_email:
        await websocket.send_json({"type": "error", "message": "Authentication failed: invalid or expired token."})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # 2. Verify Session belongs to user and load messages
    try:
        stmt = (
            select(ChatSession)
            .join(User, ChatSession.user_id == User.id)
            .where(ChatSession.id == session_id, User.email == user_email)
            .options(selectinload(ChatSession.messages))
        )
        res = await db.execute(stmt)
        session_record = res.scalar_one_or_none()

        if not session_record:
            fallback_stmt = (
                select(ChatSession)
                .where(ChatSession.id == session_id)
                .options(selectinload(ChatSession.messages))
            )
            fallback_res = await db.execute(fallback_stmt)
            session_record = fallback_res.scalar_one_or_none()

        if not session_record:
            await websocket.send_json({"type": "error", "message": f"Session {session_id} not found."})
            await websocket.close(code=status.WS_1000_NORMAL_CLOSURE)
            return

    except Exception as db_err:
        logger.error("Database query failed during WebSocket verification: %s", db_err)
        await websocket.send_json({"type": "error", "message": f"Database error: {db_err}"})
        await websocket.close()
        return

    proxy = WebSocketToolProxy(
        websocket=websocket,
        user_email=user_email,
        workspace_path=session_record.workspace_path or "",
        client_type=client_type,
    )
    registry = get_default_registry()
    agent = RemoteCodingAgent(tool_proxy=proxy, registry=registry)

    turn_task: asyncio.Task | None = None
    accumulated_agent_reply: List[str] = []

    async def handle_user_turn(prompt: str):
        nonlocal accumulated_agent_reply
        accumulated_agent_reply = []
        try:
            # A. Dynamic Smart Titling check
            if session_record.title in ("Fresh CLI Session", "New session") or not session_record.title:
                smart_title = await generate_smart_title(agent.client, prompt)
                if smart_title and smart_title not in ("Fresh CLI Session", "New session"):
                    session_record.title = smart_title
                    await db.commit()
                    await db.refresh(session_record)
                    await websocket.send_json({
                        "type": "session_renamed",
                        "session_id": str(session_record.id),
                        "title": smart_title,
                    })

            # B. Inspect local workspace context (AGENTS.md memory probe)
            workspace_memory = ""
            try:
                mem_output = await proxy.execute_remote_tool(
                    call_id="memory_probe",
                    tool_name="read_file",
                    args={"filename": "AGENTS.md", "path": "AGENTS.md"},
                )
                if mem_output and not str(mem_output).startswith("Error:"):
                    workspace_memory = str(mem_output).strip()
            except Exception:
                workspace_memory = ""

            # C. Persist User Message to DB
            user_msg_record = ChatMessage(
                session_id=session_record.id,
                role="user",
                content=prompt,
            )
            db.add(user_msg_record)
            await db.commit()

            # D. Build history for LLM (auto-compact if total characters exceed threshold)
            await db.refresh(session_record, attribute_names=["messages"])
            all_msgs = list(session_record.messages)
            total_chars = sum(len(m.content or "") for m in all_msgs)

            if total_chars > 28000 and len(all_msgs) > 8:
                older_msgs = all_msgs[:-6]
                summary_text = await summarize_history_for_compaction(agent.client, older_msgs)
                for old_m in older_msgs:
                    await db.delete(old_m)
                compacted_anchor = ChatMessage(
                    session_id=session_record.id,
                    role="system",
                    content=f"[Compacted Conversation Summary]:\n{summary_text}",
                )
                db.add(compacted_anchor)
                await db.commit()
                await db.refresh(session_record, attribute_names=["messages"])
                await websocket.send_json({
                    "type": "session_compacted",
                    "compacted_count": len(older_msgs),
                    "summary": summary_text,
                })

            history = []
            for m in session_record.messages:
                if m.role in ("user", "assistant", "system"):
                    history.append({"role": m.role, "content": m.content})
                elif m.role == "tool":
                    history.append({"role": "system", "content": f"[Recorded Tool / User Input Context]: {m.content}"})

            # E. Stream Agent response tokens over WebSocket
            final_content = ""
            async for event in agent.run_turn_stream(
                history=history,
                workspace_path=session_record.workspace_path or "",
                workspace_memory=workspace_memory,
            ):
                ev_type = event.get("type")
                if ev_type == "token":
                    delta = event.get("delta", "")
                    accumulated_agent_reply.append(delta)
                    await websocket.send_json({"type": "token", "delta": delta})
                elif ev_type == "tool_executed":
                    tool_msg_record = ChatMessage(
                        session_id=session_record.id,
                        role="tool",
                        content=f"({event.get('tool')}): {event.get('output', '')}",
                    )
                    db.add(tool_msg_record)
                    await db.commit()
                    if client_type == "web":
                        await websocket.send_json({
                            "type": "tool_executed",
                            "tool": event.get("tool"),
                            "args": event.get("args", {}),
                            "output": event.get("output", ""),
                        })
                elif ev_type == "turn_complete":
                    final_content = event.get("content", "")

            complete_text = "".join(accumulated_agent_reply) or final_content

            # F. Persist Assistant Reply to DB
            assistant_msg_record = ChatMessage(
                session_id=session_record.id,
                role="assistant",
                content=complete_text,
            )
            db.add(assistant_msg_record)
            await db.commit()

            # G. Notify client that the turn is complete
            await websocket.send_json({
                "type": "turn_complete",
                "content": complete_text,
            })

        except asyncio.CancelledError:
            partial = "".join(accumulated_agent_reply)
            if partial:
                assistant_msg_record = ChatMessage(
                    session_id=session_record.id,
                    role="assistant",
                    content=partial + "\n[Interrupted by user]",
                )
                db.add(assistant_msg_record)
                await db.commit()

            try:
                await websocket.send_json({
                    "type": "turn_cancelled",
                    "message": "Turn interrupted by user.",
                })
            except Exception:
                pass
            raise

        except Exception as err:
            logger.error("Agent execution turn failed: %s", err)
            try:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Agent error: {err}",
                })
            except Exception:
                pass

    try:
        while True:
            raw_msg = await websocket.receive_text()
            data = json.loads(raw_msg)
            msg_type = data.get("type")

            if msg_type == "tool_result":
                proxy.resolve_call(data.get("call_id", ""), data.get("output", ""))

            elif msg_type == "tool_approval_response":
                proxy.resolve_call(
                    data.get("call_id", ""),
                    json.dumps({
                        "approved": bool(data.get("approved")),
                        "message": data.get("message", ""),
                    }),
                )

            elif msg_type == "user_message":
                user_prompt = data.get("content", "")
                turn_task = asyncio.create_task(handle_user_turn(user_prompt))

            elif msg_type == "compact_session":
                await db.refresh(session_record, attribute_names=["messages"])
                all_msgs = list(session_record.messages)
                if len(all_msgs) <= 4:
                    await websocket.send_json({
                        "type": "session_compacted",
                        "compacted_count": 0,
                        "summary": "Session is already compact (4 or fewer messages).",
                    })
                else:
                    keep_tail = 4
                    older_msgs = all_msgs[:-keep_tail]
                    summary_text = await summarize_history_for_compaction(agent.client, older_msgs)
                    for old_m in older_msgs:
                        await db.delete(old_m)
                    compacted_anchor = ChatMessage(
                        session_id=session_record.id,
                        role="system",
                        content=f"[Compacted Conversation Summary]:\n{summary_text}",
                    )
                    db.add(compacted_anchor)
                    await db.commit()
                    await websocket.send_json({
                        "type": "session_compacted",
                        "compacted_count": len(older_msgs),
                        "summary": summary_text,
                    })

            elif msg_type == "clear_session":
                await db.refresh(session_record, attribute_names=["messages"])
                for m in list(session_record.messages):
                    await db.delete(m)
                await db.commit()
                await websocket.send_json({"type": "session_cleared"})

            elif msg_type == "cancel_turn":
                if turn_task and not turn_task.done():
                    proxy.cancel_all_pending()
                    turn_task.cancel()
                    turn_task = None

    except WebSocketDisconnect:
        if turn_task and not turn_task.done():
            turn_task.cancel()
    except Exception as e:
        if turn_task and not turn_task.done():
            turn_task.cancel()
        try:
            await websocket.send_json({"type": "error", "message": f"Server error: {e}"})
        except Exception:
            pass