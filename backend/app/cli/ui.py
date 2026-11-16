"""Claude Code-style terminal UI with streaming, slash-command autocomplete, interactive question/permission cards, and workspace memory."""
import asyncio
import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

import websockets
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.filters import Condition
from prompt_toolkit.formatted_text import ANSI, FormattedText
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import ConditionalContainer, Float, FloatContainer, HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.widgets import Frame

from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from app.cli.client import AssistantAPIClient
from app.cli.tool_executor import LocalToolExecutor


SAFE_READ_ONLY_TOOLS = {
    "readfile",
    "read",
    "viewfile",
    "cat",
    "listdirectory",
    "listdir",
    "listfiles",
    "ls",
    "dir",
    "glob",
    "globsearch",
    "globfiles",
    "find",
    "filesearch",
    "memoryprobe",
}

SLASH_COMMANDS = [
    ("/init", "Generate or update AGENTS.md persistent workspace memory"),
    ("/memory", "View active AGENTS.md workspace memory"),
    ("/compact", "Summarize older turns to free up context window"),
    ("/clear", "Clear all messages from UI and session history"),
    ("/sessions", "Open interactive sessions list"),
    ("/new", "Create a new CLI session"),
    ("/exit", "Exit the AI Coder CLI"),
]


class ChatInputCompleter(Completer):
    """Triggers slash-command dropdown on '/' and workspace file dropdown on '@'."""

    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path).resolve()

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text_before_cursor = document.text_before_cursor
        stripped = text_before_cursor.lstrip()

        # 1. Slash command suggestions when typing '/' at start of prompt
        if stripped.startswith("/") and " " not in stripped:
            query = stripped.lower()
            for cmd, desc in SLASH_COMMANDS:
                if cmd.startswith(query):
                    yield Completion(
                        text=cmd,
                        start_position=-len(stripped),
                        display=cmd,
                        display_meta=desc,
                    )
            return

        # 2. Workspace file suggestions when typing '@' anywhere
        if "@" not in text_before_cursor:
            return

        at_index = text_before_cursor.rfind("@")
        query = text_before_cursor[at_index + 1 :].lower()

        if not self.workspace_path.exists():
            return

        try:
            for root, dirs, files in os.walk(self.workspace_path):
                dirs[:] = [d for d in dirs if d not in {".git", ".venv", "__pycache__", "node_modules"}]
                for file in files:
                    full_p = Path(root) / file
                    rel_p = str(full_p.relative_to(self.workspace_path)).replace("\\", "/")
                    if not query or query in rel_p.lower():
                        yield Completion(
                            text=rel_p,
                            start_position=-len(query),
                            display=rel_p,
                            display_meta="workspace file",
                        )
        except Exception:
            pass


class AgentTerminalUI:
    """Claude Code-style terminal UI with WebSocket-backed remote reasoning and local tool execution."""

    def __init__(self, api_client: AssistantAPIClient, workspace_path: str, initial_sessions: List[Dict[str, Any]]):
        self.api_client = api_client
        self.workspace_path = str(Path(workspace_path).resolve())
        self.sessions = initial_sessions or []
        self.current_session_idx = 0
        self.message_blocks: List[Dict[str, Any]] = []
        self._scroll_offset = 0

        # Local tool execution engine bounded to current workspace
        self.tool_executor = LocalToolExecutor(self.workspace_path)

        # Turn & Streaming State (Pillar 2)
        self.is_turn_running = False
        self._user_cancelled = False
        self.active_ws = None
        self.current_turn_task: asyncio.Task | None = None

        # Pillar 3: Interactive Selector Card & Per-Session Permissions
        self.session_approved_tools: set[str] = set()
        self.active_prompt_card: Dict[str, Any] | None = None

        self.mode = "chat"
        self.selected_picker_idx = 0

        # 1. FIXED TOP HEADER
        self.header_control = FormattedTextControl(
            text=self._render_fixed_header,
            focusable=False,
            show_cursor=False,
        )
        self.header_window = Window(
            content=self.header_control,
            height=4,
            dont_extend_height=True,
        )

        # 2. SCROLLABLE MESSAGE STREAM
        self.history_control = FormattedTextControl(
            text=self._render_chat_messages,
            focusable=False,
            show_cursor=False,
        )
        self.history_window = Window(
            content=self.history_control,
            wrap_lines=False,
            dont_extend_height=False,
        )

        # 3. SESSIONS PICKER VIEW
        self.picker_control = FormattedTextControl(
            text=self._render_sessions_picker,
            focusable=False,
            show_cursor=False,
        )
        self.picker_window = Window(
            content=self.picker_control,
            wrap_lines=False,
            dont_extend_height=False,
        )

        # 4. BOTTOM INPUT BUFFER & CARD CUSTOM INPUT BUFFER
        self.input_completer = ChatInputCompleter(self.workspace_path)
        self.input_buffer = Buffer(
            completer=self.input_completer,
            complete_while_typing=True,
            multiline=True,
        )
        self.input_window = Window(
            content=BufferControl(buffer=self.input_buffer),
            height=4,
            wrap_lines=True,
        )

        self.card_input_buffer = Buffer(
            on_text_changed=lambda _: self.app.invalidate() if hasattr(self, "app") and self.app else None
        )
        self.card_input_window = Window(
            content=BufferControl(buffer=self.card_input_buffer),
            height=1,
        )

        def _get_input_title() -> str:
            if self.active_prompt_card is not None:
                return "🟡 Awaiting your selection above (↑/↓: option | ←/→: tab | Enter: confirm | Esc: cancel)"
            if self.is_turn_running:
                return "⏳ Agent is working... (Press Ctrl+C to cancel turn | Ctrl+O: toggle tool details)"
            return "🟢 Ready › (Enter: send | \\+Enter: newline | /: commands | @: files | ←: sessions | Ctrl+O: tools)"

        self.input_frame = Frame(
            self.input_window,
            title=_get_input_title,
        )

        has_no_active_card = Condition(lambda: self.active_prompt_card is None)
        is_typing_custom_card = Condition(
            lambda: self.active_prompt_card is not None and bool(self.active_prompt_card.get("typing_custom"))
        )

        self.card_input_frame = Frame(
            self.card_input_window,
            title="✎ Type custom response and press Enter (Esc: back to options)",
        )

        chat_layout = HSplit([
            self.header_window,
            self.history_window,
            ConditionalContainer(content=self.card_input_frame, filter=is_typing_custom_card),
            ConditionalContainer(content=self.input_frame, filter=has_no_active_card),
        ])

        is_chat_mode = Condition(lambda: self.mode == "chat")
        is_picker_mode = Condition(lambda: self.mode == "sessions_picker")

        main_body = HSplit([
            ConditionalContainer(content=chat_layout, filter=is_chat_mode),
            ConditionalContainer(content=self.picker_window, filter=is_picker_mode),
        ])

        self.root_container = FloatContainer(
            content=main_body,
            floats=[
                Float(
                    xcursor=True,
                    ycursor=True,
                    content=CompletionsMenu(max_height=8),
                )
            ],
        )

        self.layout = Layout(self.root_container, focused_element=self.input_window)
        self.kb = KeyBindings()
        self._register_bindings()

        self.app = Application(
            layout=self.layout,
            key_bindings=self.kb,
            full_screen=True,
            mouse_support=False,
        )

        self._load_active_session()

    @property
    def current_session(self) -> Dict[str, Any]:
        if not self.sessions or self.current_session_idx >= len(self.sessions):
            return {}
        return self.sessions[self.current_session_idx]

    def _sync_sessions_from_api(self):
        try:
            fresh = self.api_client.list_sessions_for_workspace(self.workspace_path)
            if fresh:
                self.sessions = fresh
        except Exception:
            pass

    def _load_active_session(self):
        # Reset session-scoped tool permissions whenever switching or loading a session
        self.session_approved_tools.clear()
        self.message_blocks = []
        if not self.current_session:
            return

        try:
            detail = self.api_client.get_session_detail(self.current_session["id"])
            for msg in detail.get("messages", []):
                role = msg.get("role")
                raw_content = msg.get("content", "")

                if role == "user":
                    clean_content = raw_content
                    hidden_attachment = ""
                    if "\n--- Attached File:" in raw_content:
                        parts = raw_content.split("\n--- Attached File:", 1)
                        clean_content = parts[0].strip()
                        hidden_attachment = "--- Attached File:" + parts[1]

                    self.message_blocks.append({
                        "kind": "user",
                        "content": clean_content,
                        "attachment": hidden_attachment,
                        "is_expanded": False,
                    })

                elif role in ("assistant", "agent"):
                    self.message_blocks.append({
                        "kind": "agent",
                        "content": raw_content,
                    })

                elif role == "system" and raw_content.startswith("[Compacted Conversation Summary]:"):
                    self.message_blocks.append({
                        "kind": "compacted_summary",
                        "content": raw_content.replace("[Compacted Conversation Summary]:", "").strip(),
                    })

                elif role == "tool":
                    lines = raw_content.splitlines()
                    preview_summary = f"{len(lines)} lines returned"
                    self.message_blocks.append({
                        "kind": "tool_action",
                        "summary": f"Tool Output ({preview_summary})",
                        "details": raw_content,
                        "is_expanded": False,
                    })
        except Exception as e:
            self.message_blocks.append({"kind": "error", "content": f"Could not load session history: {e}"})

        self._scroll_to_bottom()

    def _get_console_width(self) -> int:
        cols, _ = shutil.get_terminal_size(fallback=(90, 24))
        return max(40, cols - 2)

    def _get_viewport_height(self) -> int:
        _, rows = shutil.get_terminal_size(fallback=(90, 24))
        reserved = 10 if self.active_prompt_card is None else 12
        return max(6, rows - reserved)

    def _scroll_to_bottom(self):
        """Pins the scroll offset so the newest lines at the bottom of the stream are visible."""
        if not self.message_blocks and self.active_prompt_card is None:
            self._scroll_offset = 0
            return

        rendered = self._build_rendered_stream_lines()
        total_lines = len(rendered)
        viewport_h = self._get_viewport_height()
        self._scroll_offset = max(0, total_lines - viewport_h)

    def _render_fixed_header(self) -> FormattedText:
        width = self._get_console_width()
        raw_title = (self.current_session.get("title") or "Fresh CLI Session").strip()
        clean_title = raw_title.replace("**", "").replace("*", "").replace("`", "").strip()

        total = len(self.sessions)
        idx_str = f"[{self.current_session_idx + 1}/{total}]" if total > 0 else "[1/1]"
        status_pill = " [⏳ WORKING] " if self.is_turn_running else " [🟢 IDLE] "

        line1 = [
            ("bold bg:#d7af00 fg:#000000", " AI CODER "),
            ("bold fg:#ffffff", " v0.1.0 (local daemon)"),
            ("bold fg:#ffd700" if self.is_turn_running else "fg:#00af5f", f"{status_pill}\n"),
        ]

        ws_text = f"📁 Workspace: {self.workspace_path}"
        line2 = [
            ("fg:#888888", f"{ws_text:<{width}}\n"),
        ]

        sess_label = f"⚡ Session {idx_str}: "
        sess_line = f"{sess_label}{clean_title}"
        line3 = [
            ("bold fg:#00d7d7", f"{sess_line:<{width}}\n"),
        ]

        rule_line = [
            ("fg:#555555", "─" * width + "\n"),
        ]

        return FormattedText(line1 + line2 + line3 + rule_line)

    def _render_interactive_card(self, console: Console):
        """Renders the Claude Code-style multi-question & permission selector card."""
        card = self.active_prompt_card
        if not isinstance(card, dict):
            return

        questions = card.get("questions", [])
        if not questions:
            return

        q_idx = max(0, min(int(card.get("current_q_idx", 0)), len(questions) - 1))

        active_q = questions[q_idx]
        selected_opt = card.get("selected_opt_idx", 0)
        answers = card.get("answers", {})
        typing_custom = card.get("typing_custom", False)

        body = Text()

        # Tab strip if multiple questions
        if len(questions) > 1:
            for idx, q in enumerate(questions):
                hdr = q.get("header") or f"Q{idx + 1}"
                answered_mark = "✓ " if idx in answers else ""
                if idx == q_idx:
                    body.append(f" [{answered_mark}{hdr}] ", style="bold black on bright_cyan")
                else:
                    body.append(f"  {answered_mark}{hdr}  ", style="dim")
            body.append("\n\n")

        # Question text & optional detail subtitle
        body.append(f"{active_q.get('question', '')}\n", style="bold white")
        subtitle = active_q.get("subtitle", "")
        if subtitle:
            body.append(f"{subtitle}\n", style="dim")
        body.append("\n")

        # Options + automatic final custom text option
        base_options = list(active_q.get("options", []))
        custom_opt_idx = len(base_options)

        for idx, opt_label in enumerate(base_options):
            is_sel = idx == selected_opt
            prefix = "❯ " if is_sel else "  "
            style = "bold bright_cyan" if is_sel else "white"
            body.append(f"{prefix}{idx + 1}. {opt_label}\n", style=style)

        # Final custom textbox option
        is_custom_sel = selected_opt == custom_opt_idx
        custom_prefix = "❯ " if is_custom_sel else "  "
        if is_custom_sel and typing_custom:
            body.append(
                f"{custom_prefix}{custom_opt_idx + 1}. ✎ Typing custom response in bottom box...\n",
                style="bold bright_yellow",
            )
        else:
            custom_style = "bold bright_yellow" if is_custom_sel else "dim italic"
            body.append(
                f"{custom_prefix}{custom_opt_idx + 1}. ✎ Type custom response / instructions...\n",
                style=custom_style,
            )

        # Footer navigation hints
        nav_hint = "\n↑/↓: move  •  "
        if len(questions) > 1:
            nav_hint += "←/→: switch tab  •  "
        nav_hint += "Enter: select  •  Esc: cancel"
        body.append(nav_hint, style="dim")

        card_title = card.get("title", "Interactive Prompt")
        console.print(Panel(body, title=f"[bold yellow]{card_title}[/bold yellow]", border_style="yellow"))

    def _build_rendered_stream_lines(self) -> List[str]:
        width = self._get_console_width()
        console = Console(record=True, force_terminal=True, color_system="standard", width=width)

        with console.capture() as capture:
            for item in self.message_blocks:
                kind = item.get("kind")

                if kind == "user":
                    user_header = Text("› ", style="bold cyan")
                    user_header.append(f"{item.get('content', '')}\n", style="bold white")
                    console.print(user_header)

                    attachment = item.get("attachment")
                    if attachment:
                        expanded = item.get("is_expanded", False)
                        toggle_icon = "▼" if expanded else "▶"
                        att_badge = Text(f"  {toggle_icon} [Attached Context / Files]", style="dim cyan italic")
                        console.print(att_badge)
                        if expanded:
                            console.print(Text(f"{attachment.strip()}\n", style="dim"))

                elif kind == "agent":
                    agent_badge = Text("● Agent\n", style="bold green")
                    console.print(agent_badge)
                    console.print(Markdown(item.get("content", "")))
                    console.print(Rule(style="dim"))

                elif kind == "compacted_summary":
                    console.print(
                        Panel(
                            Markdown(item.get("content", "")),
                            title="[bold cyan]🗜 Compacted Context Summary[/bold cyan]",
                            border_style="cyan",
                        )
                    )

                elif kind == "tool_action":
                    expanded = item.get("is_expanded", False)
                    toggle_icon = "▼" if expanded else "▶"
                    summary = item.get("summary", "")
                    details = item.get("details", "")

                    action_line = Text(f"{toggle_icon} ⚙ {summary}", style="yellow italic")
                    console.print(action_line)

                    if expanded and details:
                        console.print(Text(f"    {details.strip()}\n", style="dim"))

                elif kind == "thinking":
                    console.print(Text("⏳ … thinking & executing tools… (Ctrl+C to cancel)", style="italic bright_yellow"))

                elif kind == "cancelled":
                    console.print(Text("⊘ [Turn cancelled by user]\n", style="dim italic yellow"))

                elif kind == "error":
                    console.print(Text(f"✖ Error: {item.get('content', '')}\n", style="bold red"))

            # Render active Claude-style selector card at the bottom of the stream
            if self.active_prompt_card is not None:
                self._render_interactive_card(console)

        return capture.get().splitlines(keepends=True)

    def _render_chat_messages(self):
        lines = self._build_rendered_stream_lines()
        if not lines:
            return ANSI("")

        self._scroll_offset = max(0, min(self._scroll_offset, len(lines) - 1))
        visible_lines = lines[self._scroll_offset :]
        return ANSI("".join(visible_lines))

    def _render_sessions_picker(self):
        width = self._get_console_width()
        console = Console(record=True, force_terminal=True, color_system="standard", width=width)

        with console.capture() as capture:
            title_text = Text()
            title_text.append(" █ SESSIONS ", style="bold black on bright_yellow")
            title_text.append("  (↑/↓: navigate | Enter/→: resume | Ctrl+N: new | Esc/→: back to chat)\n", style="dim")
            console.print(title_text)
            console.print(Rule(style="dim yellow"))

            table = Table(box=None, expand=True, show_header=True, header_style="bold dim")
            table.add_column("Session Title", ratio=4)
            table.add_column("Status", ratio=2)
            table.add_column("Workspace", ratio=3)
            table.add_column("Updated", ratio=2, justify="right")

            for i, sess in enumerate(self.sessions):
                is_selected = i == self.selected_picker_idx
                prefix = "❯ " if is_selected else "  "
                style = "bold white on dark_blue" if is_selected else "dim"

                sess_title = sess.get("title") or "Untitled Session"
                updated_at = sess.get("updated_at") or sess.get("created_at") or ""
                time_str = updated_at[:10] if updated_at else "-"

                status_badge = "[green]● Active[/green]" if i == self.current_session_idx else "[dim]Archived[/dim]"
                ws_name = Path(sess.get("workspace_path", "")).name or "workspace"

                table.add_row(
                    f"{prefix}{sess_title}",
                    status_badge,
                    ws_name,
                    time_str,
                    style=style,
                )

            console.print(table)

        return ANSI(capture.get())

    def _scroll_to_start_of_latest(self):
        if len(self.message_blocks) <= 1:
            self._scroll_offset = 0
            return

        width = self._get_console_width()
        console = Console(record=True, force_terminal=True, width=width)
        with console.capture() as capture:
            for item in self.message_blocks[:-1]:
                kind = item.get("kind")
                if kind == "user":
                    console.print(Text(f"› {item.get('content')}\n"))
                elif kind == "agent":
                    console.print(Text("● Agent\n"))
                    console.print(Markdown(item.get("content", "")))
                    console.print(Rule())
                elif kind == "compacted_summary":
                    console.print(Text(f"[Compacted Summary]\n{item.get('content', '')}\n"))
                elif kind == "tool_action":
                    console.print(Text(f"⚙ {item.get('summary', '')}"))
                elif kind == "error":
                    console.print(Text(f"✖ Error: {item.get('content')}\n"))

        prior_lines = capture.get().splitlines()
        self._scroll_offset = max(0, len(prior_lines))

    def _focus_chat_input(self):
        """Safely returns keyboard focus to the bottom chat input window."""
        if hasattr(self, "layout") and self.layout:
            try:
                self.layout.focus(self.input_window)
            except Exception:
                pass

    def _resolve_interactive_card_selection(self):
        """Handles Enter press inside the Claude-style interactive card."""
        card = self.active_prompt_card
        if not card:
            return

        questions = card.get("questions", [])
        q_idx = card.get("current_q_idx", 0)
        active_q = questions[q_idx]
        base_options = list(active_q.get("options", []))
        custom_opt_idx = len(base_options)
        selected_opt = card.get("selected_opt_idx", 0)

        # If user selected the custom textbox option
        if selected_opt == custom_opt_idx:
            if not card.get("typing_custom"):
                card["typing_custom"] = True
                self.card_input_buffer.reset()
                if hasattr(self, "layout") and self.layout:
                    try:
                        self.layout.focus(self.card_input_window)
                    except Exception:
                        pass
                self._scroll_to_bottom()
                self.app.invalidate()
                return
            else:
                custom_text = self.card_input_buffer.text.strip()
                if not custom_text:
                    return
                chosen_value = custom_text
                self.card_input_buffer.reset()
                card["typing_custom"] = False
                self._focus_chat_input()
        else:
            chosen_value = base_options[selected_opt]

        card["answers"][q_idx] = chosen_value

        # Move to next unanswered question if multi-question prompt
        if len(questions) > 1 and len(card["answers"]) < len(questions):
            for next_i in range(len(questions)):
                if next_i not in card["answers"]:
                    card["current_q_idx"] = next_i
                    card["selected_opt_idx"] = 0
                    break
            self._scroll_to_bottom()
            self.app.invalidate()
            return

        # All questions answered -> resolve Future
        future: asyncio.Future = card["future"]
        answers_copy = dict(card["answers"])
        self.active_prompt_card = None
        self._focus_chat_input()
        if not future.done():
            future.set_result(answers_copy)
        self._scroll_to_bottom()
        self.app.invalidate()

    def _create_fresh_session(self):
        try:
            self.session_approved_tools.clear()
            self.api_client.create_session(self.workspace_path, "Fresh CLI Session")
            self._sync_sessions_from_api()
            self.current_session_idx = 0
            self.mode = "chat"
            self._load_active_session()
            self.app.renderer.clear()
            self.app.invalidate()
        except Exception as e:
            self.message_blocks.append({"kind": "error", "content": f"Failed to create new session: {e}"})
            self.app.invalidate()

    def _register_bindings(self):
        is_card_open = Condition(lambda: self.active_prompt_card is not None)
        has_completion_menu = Condition(lambda: bool(self.input_buffer.complete_state))

        @self.kb.add("c-c")
        def _exit(event):
            if self.active_prompt_card is not None:
                future = self.active_prompt_card.get("future")
                self.active_prompt_card = None
                self.card_input_buffer.reset()
                self._focus_chat_input()
                if future and not future.done():
                    future.set_result(None)
            if self.is_turn_running:
                asyncio.create_task(self._cancel_active_turn())
                return
            event.app.exit()

        # Ctrl+O: Toggle expand/collapse of the latest tool call or context block
        @self.kb.add("c-o")
        def _toggle_details(event):
            if self.mode == "chat":
                for block in reversed(self.message_blocks):
                    if block.get("kind") in ("tool_action", "user") and ("details" in block or "attachment" in block):
                        block["is_expanded"] = not block.get("is_expanded", False)
                        break
                self. _scroll_to_bottom()
                event.app.invalidate()

        @self.kb.add("c-s")
        def _toggle_sessions(event):
            if self.active_prompt_card is not None:
                return
            self._sync_sessions_from_api()
            if self.mode == "chat":
                self.mode = "sessions_picker"
                self.selected_picker_idx = self.current_session_idx
            else:
                self.mode = "chat"
            event.app.invalidate()

        # Left Arrow: switch question tabs in interactive card, or open sessions picker when input is empty
        @self.kb.add("left", filter=is_card_open, eager=True)
        def _card_left(event):
            card = self.active_prompt_card
            if card and not card.get("typing_custom"):
                questions = card.get("questions", [])
                if len(questions) > 1:
                    card["current_q_idx"] = (card.get("current_q_idx", 0) - 1) % len(questions)
                    card["selected_opt_idx"] = 0
                    self._scroll_to_bottom()
                    event.app.invalidate()

        @self.kb.add("left", filter=~is_card_open)
        def _nav_to_sessions(event):
            if self.mode == "chat" and not self.input_buffer.text:
                self._sync_sessions_from_api()
                self.mode = "sessions_picker"
                self.selected_picker_idx = self.current_session_idx
                event.app.invalidate()
            elif self.mode == "chat":
                self.input_buffer.cursor_left()

        # Right Arrow: switch question tabs in interactive card, or resume session from picker
        @self.kb.add("right", filter=is_card_open, eager=True)
        def _card_right(event):
            card = self.active_prompt_card
            if card and not card.get("typing_custom"):
                questions = card.get("questions", [])
                if len(questions) > 1:
                    card["current_q_idx"] = (card.get("current_q_idx", 0) + 1) % len(questions)
                    card["selected_opt_idx"] = 0
                    self._scroll_to_bottom()
                    event.app.invalidate()

        @self.kb.add("right", filter=~is_card_open)
        def _nav_to_chat(event):
            if self.mode == "sessions_picker":
                self.current_session_idx = self.selected_picker_idx
                self.mode = "chat"
                self._load_active_session()
                event.app.renderer.clear()
                event.app.invalidate()
            elif self.mode == "chat":
                self.input_buffer.cursor_right()

        @self.kb.add("escape", filter=is_card_open, eager=True)
        def _card_escape(event):
            card = self.active_prompt_card
            if card:
                if card.get("typing_custom"):
                    card["typing_custom"] = False
                    self.card_input_buffer.reset()
                    self._focus_chat_input()
                    self._scroll_to_bottom()
                    event.app.invalidate()
                    return
                future = card.get("future")
                self.active_prompt_card = None
                self._focus_chat_input()
                if future and not future.done():
                    future.set_result(None)
                self._scroll_to_bottom()
                event.app.invalidate()

        @self.kb.add("escape", filter=~is_card_open)
        def _close_picker_or_menu(event):
            if self.input_buffer.complete_state:
                self.input_buffer.cancel_completion()
                event.app.invalidate()
                return
            if self.mode == "sessions_picker":
                self.mode = "chat"
                event.app.invalidate()

        @self.kb.add("c-n")
        def _new_session(event):
            if self.active_prompt_card is not None:
                return
            self._create_fresh_session()

        @self.kb.add("up", filter=is_card_open, eager=True)
        def _card_up(event):
            card = self.active_prompt_card
            if card and not card.get("typing_custom"):
                q_idx = card.get("current_q_idx", 0)
                total_opts = len(card["questions"][q_idx].get("options", [])) + 1
                card["selected_opt_idx"] = (card.get("selected_opt_idx", 0) - 1) % total_opts
                self._scroll_to_bottom()
                event.app.invalidate()

        @self.kb.add("up", filter=~is_card_open & ~has_completion_menu)
        def _nav_up(event):
            if self.mode == "sessions_picker":
                if self.selected_picker_idx > 0:
                    self.selected_picker_idx -= 1
                    event.app.invalidate()
            elif self.mode == "chat":
                event.current_buffer.cursor_up()

        @self.kb.add("down", filter=is_card_open, eager=True)
        def _card_down(event):
            card = self.active_prompt_card
            if card and not card.get("typing_custom"):
                q_idx = card.get("current_q_idx", 0)
                total_opts = len(card["questions"][q_idx].get("options", [])) + 1
                card["selected_opt_idx"] = (card.get("selected_opt_idx", 0) + 1) % total_opts
                self._scroll_to_bottom()
                event.app.invalidate()

        @self.kb.add("down", filter=~is_card_open & ~has_completion_menu)
        def _nav_down(event):
            if self.mode == "sessions_picker":
                if self.selected_picker_idx < len(self.sessions) - 1:
                    self.selected_picker_idx += 1
                    event.app.invalidate()
            elif self.mode == "chat":
                event.current_buffer.cursor_down()

        # Standard CLI Ctrl+U: Delete current line backwards, or if current line is empty, delete the line above
        @self.kb.add("c-u", filter=~is_card_open)
        def _kill_line_backwards(event):
            buf = event.current_buffer
            text_before = buf.document.text_before_cursor
            if not text_before:
                return
            col = buf.document.cursor_position_col
            if col > 0:
                buf.delete_before_cursor(count=col)
            else:
                # Current line is empty (cursor is right after a '\n'): delete the '\n' and the previous line
                prev_newline = text_before[:-1].rfind("\n")
                delete_count = len(text_before) if prev_newline == -1 else (len(text_before) - 1 - prev_newline)
                buf.delete_before_cursor(count=delete_count)

        # Alt+Enter / Esc+Enter / Ctrl+J: Insert a newline directly without submitting
        @self.kb.add("escape", "enter", filter=~is_card_open)
        @self.kb.add("c-j", filter=~is_card_open)
        def _insert_newline(event):
            if self.mode == "chat":
                event.current_buffer.insert_text("\n")

        # Keyboard Scroll bindings (PgUp / PgDn or Esc+Up / Esc+Down)
        @self.kb.add("pageup")
        @self.kb.add("escape", "up")
        def _scroll_up(event):
            self._scroll_offset = max(0, self._scroll_offset - 6)
            event.app.invalidate()

        @self.kb.add("pagedown")
        @self.kb.add("escape", "down")
        def _scroll_down(event):
            self._scroll_offset += 6
            event.app.invalidate()

        @self.kb.add("enter", eager=True)
        def _submit(event):
            if self.active_prompt_card is not None:
                self._resolve_interactive_card_selection()
                return

            if self.mode == "sessions_picker":
                self.current_session_idx = self.selected_picker_idx
                self.mode = "chat"
                self._load_active_session()
                event.app.renderer.clear()
                event.app.invalidate()
                return

            # Backslash + Enter (\ + Enter) inserts a new line instead of submitting
            doc = self.input_buffer.document
            if doc.text_before_cursor.endswith("\\"):
                self.input_buffer.delete_before_cursor(count=1)
                self.input_buffer.insert_text("\n")
                return

            # Prevent submitting a second prompt while a turn is already running
            if self.is_turn_running:
                return

            # If a slash-command or @file dropdown is open, accept the highlighted completion first
            if self.input_buffer.complete_state:
                comp = self.input_buffer.complete_state.current_completion
                if comp:
                    self.input_buffer.apply_completion(comp)
                else:
                    self.input_buffer.cancel_completion()
                if self.input_buffer.text.strip().lower() not in {c for c, _ in SLASH_COMMANDS}:
                    return

            text = self.input_buffer.text.strip()
            if not text:
                return

            cmd_lower = text.lower()
            if cmd_lower in ("exit", "quit", "/exit", "/quit"):
                event.app.exit()
                return

            if cmd_lower in ("clear", "/clear", "cls"):
                self.input_buffer.reset()
                asyncio.create_task(self._clear_active_session())
                return

            if cmd_lower == "/sessions":
                self.input_buffer.reset()
                self._sync_sessions_from_api()
                self.mode = "sessions_picker"
                self.selected_picker_idx = self.current_session_idx
                event.app.invalidate()
                return

            if cmd_lower == "/new":
                self.input_buffer.reset()
                self._create_fresh_session()
                return

            if cmd_lower == "/compact":
                self.input_buffer.reset()
                asyncio.create_task(self._compact_active_session())
                return

            if cmd_lower == "/memory":
                self.input_buffer.reset()
                mem_file = Path(self.workspace_path) / "AGENTS.md"
                if mem_file.is_file():
                    mem_text = mem_file.read_text(encoding="utf-8", errors="replace").strip()
                    self.message_blocks.append({
                        "kind": "compacted_summary",
                        "content": f"**Workspace Memory (`AGENTS.md`):**\n\n{mem_text}",
                    })
                else:
                    self.message_blocks.append({
                        "kind": "error",
                        "content": "No AGENTS.md found in this workspace yet. Run /init to generate one.",
                    })
                self._scroll_to_bottom()
                event.app.invalidate()
                return

            if cmd_lower == "/init":
                self.input_buffer.reset()
                init_prompt = (
                    "Inspect the files and structure of this workspace using list_files and read_file, "
                    "then create or update `AGENTS.md` in the workspace root with concise, high-signal project memory: "
                    "tech stack, key files/directories, run/test commands, and coding conventions."
                )
                self.message_blocks.append({
                    "kind": "user",
                    "content": "/init (Generate workspace AGENTS.md memory)",
                    "attachment": "",
                    "is_expanded": False,
                })
                self._scroll_to_start_of_latest()
                event.app.invalidate()
                self.current_turn_task = asyncio.create_task(self._process_turn(init_prompt))
                return

            self.input_buffer.reset()
            expanded_text, attachment_text = self._expand_file_mentions(text)

            self.message_blocks.append({
                "kind": "user",
                "content": text,
                "attachment": attachment_text,
                "is_expanded": False,
            })
            self._scroll_to_start_of_latest()
            event.app.invalidate()

            self.current_turn_task = asyncio.create_task(self._process_turn(expanded_text))

    def _expand_file_mentions(self, text: str) -> tuple:
        words = text.split()
        attachments = []
        for word in words:
            if word.startswith("@") and len(word) > 1:
                rel_path = word[1:]
                full_path = Path(self.workspace_path) / rel_path
                if full_path.is_file():
                    try:
                        content = full_path.read_text(encoding="utf-8", errors="replace")
                        attachments.append(f"\n--- Attached File: {rel_path} ---\n{content}\n")
                    except Exception:
                        pass
        joined_att = "".join(attachments)
        if joined_att:
            return (text + "\n" + joined_att, joined_att)
        return (text, "")

    def _get_ws_url(self, session_id: str) -> str:
        base = self.api_client.base_url
        ws_base = base.replace("https://", "wss://").replace("http://", "ws://")
        token = self.api_client.token
        return f"{ws_base}/api/ws/agent?token={token}&session_id={session_id}"

    async def _present_interactive_card(self, title: str, questions: List[Dict[str, Any]]) -> Dict[int, str] | None:
        """Displays a Claude Code-style interactive selector card and awaits user selection."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()

        self.card_input_buffer.reset()
        self.active_prompt_card = {
            "title": title,
            "questions": questions,
            "current_q_idx": 0,
            "selected_opt_idx": 0,
            "answers": {},
            "typing_custom": False,
            "future": future,
        }
        self._scroll_to_bottom()
        self.app.invalidate()

        try:
            return await future
        finally:
            self.active_prompt_card = None
            self.card_input_buffer.reset()
            self._focus_chat_input()
            self._scroll_to_bottom()
            self.app.invalidate()

    async def _handle_ask_user_tool(self, tool_args: Dict[str, Any]) -> str:
        """Handles the `ask_user` tool via the Claude-style multi-question interactive card."""
        raw_questions = tool_args.get("questions") or []
        if not raw_questions:
            q_text = tool_args.get("question", "Please provide your input:")
            opts = tool_args.get("options") or ["Yes", "No"]
            raw_questions = [{"header": "Question", "question": q_text, "options": opts}]

        answers = await self._present_interactive_card(
            title="Clarifying Questions",
            questions=raw_questions,
        )
        if answers is None:
            return "User cancelled the question prompt."

        formatted_lines = ["User responses:"]
        for idx, q in enumerate(raw_questions):
            header = q.get("header") or q.get("question") or f"Question {idx + 1}"
            ans = answers.get(idx, "(no response)")
            formatted_lines.append(f"- {header}: {ans}")
        return "\n".join(formatted_lines)

    async def _request_tool_approval(self, tool_name: str, tool_args: Dict[str, Any]) -> tuple[bool, str]:
        """Pauses mutating tools for approval using the Claude-style selector card with custom instructions."""
        norm_name = tool_name.lower().replace("_", "").replace("-", "").replace(".", "")
        if norm_name in SAFE_READ_ONLY_TOOLS or norm_name in self.session_approved_tools:
            return True, ""

        arg_preview = json.dumps(tool_args)
        if len(arg_preview) > 100:
            arg_preview = arg_preview[:97] + "..."

        questions = [
            {
                "header": "Permission",
                "question": f"Allow execution of {tool_name}?",
                "subtitle": f"Args: {arg_preview}",
                "options": [
                    "Allow once",
                    f"Always allow '{tool_name}' during this session",
                    "Deny",
                ],
            }
        ]

        answers = await self._present_interactive_card(
            title=f"⚠ Tool Permission: {tool_name}",
            questions=questions,
        )
        if answers is None:
            return False, f"User cancelled or denied execution of '{tool_name}'."

        choice = answers.get(0, "Deny")
        if choice == "Allow once":
            return True, ""
        if choice.startswith("Always allow"):
            self.session_approved_tools.add(norm_name)
            return True, ""
        if choice == "Deny":
            return False, f"User denied permission to execute '{tool_name}'."

        return False, f"User declined '{tool_name}' with custom instructions: {choice}"

    async def _clear_active_session(self):
        """Deletes all messages in the active session from DB and wipes the UI screen."""
        active_id = self.current_session.get("id")
        self.message_blocks = []
        self._scroll_offset = 0
        self.app.renderer.clear()
        self.app.invalidate()

        if not active_id:
            return

        ws_url = self._get_ws_url(active_id)
        try:
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"type": "clear_session"}))
                await ws.recv()
        except Exception as e:
            self.message_blocks.append({"kind": "error", "content": f"Failed to clear server history: {e}"})
            self.app.invalidate()

    async def _compact_active_session(self):
        """Requests server-side session compaction over WebSocket and refreshes history."""
        active_id = self.current_session.get("id")
        if not active_id:
            return

        self.message_blocks.append({"kind": "thinking", "content": ""})
        self._scroll_to_bottom()
        self.app.invalidate()

        ws_url = self._get_ws_url(active_id)
        try:
            async with websockets.connect(ws_url) as ws:
                await ws.send(json.dumps({"type": "compact_session"}))
                raw_frame = await ws.recv()
                data = json.loads(raw_frame)

                if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                    self.message_blocks.pop()

                if data.get("type") == "session_compacted":
                    count = data.get("compacted_count", 0)
                    summary = data.get("summary", "")
                    if count > 0:
                        self._load_active_session()
                    else:
                        self.message_blocks.append({
                            "kind": "compacted_summary",
                            "content": summary,
                        })
                elif data.get("type") == "error":
                    self.message_blocks.append({
                        "kind": "error",
                        "content": data.get("message", "Compaction failed"),
                    })
        except Exception as e:
            if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                self.message_blocks.pop()
            self.message_blocks.append({"kind": "error", "content": f"Compaction failed: {e}"})

        self._scroll_to_bottom()
        self.app.invalidate()

    async def _cancel_active_turn(self):
        """Immediately aborts the active turn locally and notifies the backend."""
        self._user_cancelled = True
        self.active_prompt_card = None
        if self.active_ws:
            try:
                await self.active_ws.send(json.dumps({"type": "cancel_turn"}))
            except Exception:
                pass
        if self.current_turn_task and not self.current_turn_task.done():
            self.current_turn_task.cancel()

    async def _process_turn(self, user_prompt: str):
        """Processes turn through WebSocket bridge with real-time token streaming, approvals, and cancellation."""
        self.is_turn_running = True
        self._user_cancelled = False
        self.message_blocks.append({"kind": "thinking", "content": ""})
        self._scroll_to_bottom()
        self.app.invalidate()

        active_id = self.current_session.get("id")
        if not active_id:
            self.is_turn_running = False
            if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                self.message_blocks.pop()
            self.message_blocks.append({"kind": "error", "content": "No active session found. Press Ctrl+N to create one."})
            self._scroll_to_bottom()
            self.app.invalidate()
            return

        ws_url = self._get_ws_url(active_id)
        streaming_block: Dict[str, Any] | None = None

        try:
            async with websockets.connect(ws_url) as ws:
                self.active_ws = ws

                # 1. Send the user prompt
                await ws.send(json.dumps({"type": "user_message", "content": user_prompt}))

                # 2. Event loop processing incoming frames
                while True:
                    raw_frame = await ws.recv()
                    data = json.loads(raw_frame)
                    msg_type = data.get("type")

                    if msg_type == "tool_call":
                        call_id = data.get("call_id", "")
                        tool_name = data.get("tool", "")
                        tool_args = data.get("args", {})

                        # Reset streaming_block so post-tool tokens render in a new block below the tool action
                        streaming_block = None

                        # Handle interactive `ask_user` clarifying questions
                        if tool_name.lower().replace("_", "") == "askuser":
                            if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                                self.message_blocks.pop()
                            result_str = await self._handle_ask_user_tool(tool_args)
                            self.message_blocks.append({
                                "kind": "tool_action",
                                "summary": "Answered clarifying questions",
                                "details": result_str,
                                "is_expanded": False,
                            })
                            self.message_blocks.append({"kind": "thinking", "content": ""})
                            self._scroll_to_bottom()
                            self.app.invalidate()
                            await ws.send(json.dumps({
                                "type": "tool_result",
                                "call_id": call_id,
                                "output": result_str,
                            }))
                            continue

                        # Internal system context probes (AGENTS.md) run silently
                        is_internal_probe = str(call_id).endswith("_probe") or tool_name == "memory_probe"

                        tool_block = None
                        if not is_internal_probe:
                            arg_preview = json.dumps(tool_args)
                            if len(arg_preview) > 50:
                                arg_preview = arg_preview[:47] + "..."
                            summary_label = f"Executing local {tool_name}({arg_preview})"

                            tool_block = {
                                "kind": "tool_action",
                                "summary": summary_label,
                                "details": "",
                                "is_expanded": False,
                            }
                            if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                                self.message_blocks.insert(-1, tool_block)
                            else:
                                self.message_blocks.append(tool_block)
                            self._scroll_to_bottom()
                            self.app.invalidate()

                            # Pillar 3: Interactive approval gate for mutating tools
                            approved, custom_reply = await self._request_tool_approval(tool_name, tool_args)
                            if not approved:
                                if tool_block:
                                    tool_block["summary"] = f"Declined {tool_name}({arg_preview})"
                                    tool_block["details"] = custom_reply
                                if not self.message_blocks or self.message_blocks[-1].get("kind") != "thinking":
                                    self.message_blocks.append({"kind": "thinking", "content": ""})
                                self._scroll_to_bottom()
                                self.app.invalidate()
                                await ws.send(json.dumps({
                                    "type": "tool_result",
                                    "call_id": call_id,
                                    "output": custom_reply,
                                }))
                                continue

                        # Execute approved tool on local disk / shell
                        result_str = await self.tool_executor.execute(tool_name, tool_args)
                        if tool_block:
                            tool_block["details"] = result_str

                        if not is_internal_probe:
                            if not self.message_blocks or self.message_blocks[-1].get("kind") != "thinking":
                                self.message_blocks.append({"kind": "thinking", "content": ""})
                            self._scroll_to_bottom()
                            self.app.invalidate()

                        await ws.send(json.dumps({
                            "type": "tool_result",
                            "call_id": call_id,
                            "output": result_str,
                        }))

                    elif msg_type == "token":
                        delta = data.get("delta", "")
                        if not delta:
                            continue

                        if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                            self.message_blocks.pop()

                        if streaming_block is None:
                            streaming_block = {"kind": "agent", "content": ""}
                            self.message_blocks.append(streaming_block)

                        streaming_block["content"] += delta
                        self._scroll_to_bottom()
                        self.app.invalidate()

                    elif msg_type in ("turn_complete", "agent_message"):
                        if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                            self.message_blocks.pop()

                        final_text = data.get("content", "")
                        if streaming_block is not None:
                            if final_text and len(final_text) > len(streaming_block["content"]):
                                streaming_block["content"] = final_text
                        elif final_text:
                            self.message_blocks.append({"kind": "agent", "content": final_text})
                        break

                    elif msg_type == "turn_cancelled":
                        if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                            self.message_blocks.pop()
                        self.message_blocks.append({"kind": "cancelled", "content": ""})
                        break

                    elif msg_type == "session_renamed":
                        new_title = data.get("title")
                        target_id = str(data.get("session_id") or "")
                        if new_title:
                            clean_t = str(new_title).replace("**", "").replace("*", "").replace("`", "").strip()
                            if self.current_session:
                                self.current_session["title"] = clean_t
                            for s in self.sessions:
                                if str(s.get("id") or "") == target_id:
                                    s["title"] = clean_t
                                    break
                            if hasattr(self, "app") and self.app:
                                self.app.renderer.clear()
                                self.app.invalidate()

                    elif msg_type == "session_compacted":
                        summary = data.get("summary", "")
                        if summary:
                            compacted_block = {
                                "kind": "compacted_summary",
                                "content": summary,
                            }
                            if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                                self.message_blocks.insert(-1, compacted_block)
                            else:
                                self.message_blocks.append(compacted_block)
                            self._scroll_to_bottom()
                            self.app.invalidate()

                    elif msg_type == "error":
                        if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                            self.message_blocks.pop()
                        self.message_blocks.append({"kind": "error", "content": data.get("message", "Unknown error")})
                        break

        except asyncio.CancelledError:
            if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                self.message_blocks.pop()
            self.message_blocks.append({"kind": "cancelled", "content": ""})

        except Exception as e:
            if self.message_blocks and self.message_blocks[-1].get("kind") == "thinking":
                self.message_blocks.pop()
            if self._user_cancelled or isinstance(e, websockets.exceptions.ConnectionClosedOK):
                self.message_blocks.append({"kind": "cancelled", "content": ""})
            elif self.is_turn_running:
                self.message_blocks.append({"kind": "error", "content": f"WebSocket error: {e}"})

        finally:
            self.is_turn_running = False
            self._user_cancelled = False
            self.active_prompt_card = None
            self.active_ws = None
            self.current_turn_task = None
            self._focus_chat_input()
            self._scroll_to_bottom()
            self.app.invalidate()

    def run(self):
        try:
            self.app.run()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass