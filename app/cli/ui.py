import asyncio
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import Float, FloatContainer, HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.widgets import Frame

from rich.console import Console
from rich.markdown import Markdown
from rich.rule import Rule
from rich.text import Text


class WorkspaceFileCompleter(Completer):
    """Triggers file dropdown list whenever '@' is typed."""

    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path).resolve()

    def get_completions(self, document: Document, complete_event: CompleteEvent):
        text_before_cursor = document.text_before_cursor

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
                        )
        except Exception:
            pass


class AgentTerminalUI:
    """Full-screen terminal interface with floating @file completions menu and clean layout."""

    def __init__(self, agent: Any, workspace_path: str):
        self.agent = agent
        self.workspace_path = str(Path(workspace_path).resolve())
        self.history: List[Dict[str, Any]] = []

        self.message_blocks: List[tuple] = [
            ("banner", f"Autonomous Coding Agent\nWorkspace: {self.workspace_path}")
        ]
        self._scroll_offset = 0

        # Viewport control
        self.history_control = FormattedTextControl(
            text=self._render_all_content,
            focusable=False,
            show_cursor=False,
        )

        self.history_window = Window(
            content=self.history_control,
            wrap_lines=False,
            dont_extend_height=False,
        )

        # Bottom Input Area with @File Completer
        self.file_completer = WorkspaceFileCompleter(self.workspace_path)
        self.input_buffer = Buffer(
            completer=self.file_completer,
            complete_while_typing=True,
        )
        self.input_window = Window(
            content=BufferControl(buffer=self.input_buffer),
            height=3,
        )
        self.input_frame = Frame(
            self.input_window,
            title="Input (Enter: send | @: attach file | PgUp/PgDn: scroll | Ctrl+C: exit)",
        )

        # Base layout: history top, input bottom
        main_hsplit = HSplit([
            self.history_window,
            self.input_frame,
        ])

        # FloatContainer: displays the floating popup completions menu right above the cursor
        self.root_container = FloatContainer(
            content=main_hsplit,
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

    def _get_console_width(self) -> int:
        cols, _ = shutil.get_terminal_size(fallback=(80, 24))
        return max(35, cols - 4)

    def _render_all_content(self):
        width = self._get_console_width()
        console = Console(
            record=True,
            force_terminal=True,
            color_system="standard",
            width=width,
        )

        with console.capture() as capture:
            for kind, content in self.message_blocks:
                if kind == "banner":
                    banner_text = Text()
                    banner_text.append("● Autonomous Coding Agent\n", style="bold green")
                    banner_text.append("Workspace: ", style="dim")
                    banner_text.append(f"{self.workspace_path}\n", style="cyan")
                    console.print(banner_text)
                    console.print(Rule(style="dim green"))
                elif kind == "user":
                    user_text = Text()
                    user_text.append("› You\n", style="bold cyan")
                    user_text.append(f"{content}\n", style="white")
                    console.print(user_text)
                elif kind == "agent":
                    agent_header = Text("● Agent\n", style="bold green")
                    console.print(agent_header)
                    console.print(Markdown(content))
                    console.print(Rule(style="dim"))
                elif kind == "thinking":
                    console.print(Text("… thinking…", style="italic dim"))
                elif kind == "error":
                    console.print(Text(f"Error: {content}\n", style="bold red"))

        rendered_str = capture.get()
        lines = rendered_str.splitlines(keepends=True)
        if not lines:
            return ANSI("")

        self._scroll_offset = max(0, min(self._scroll_offset, len(lines) - 1))
        visible_lines = lines[self._scroll_offset :]
        return ANSI("".join(visible_lines))

    def _scroll_to_bottom(self):
        width = self._get_console_width()
        console = Console(record=True, force_terminal=True, width=width)
        with console.capture() as capture:
            for kind, content in self.message_blocks:
                if kind == "agent":
                    console.print(Markdown(content))
                else:
                    console.print(content)
        lines = capture.get().splitlines()
        _, term_rows = shutil.get_terminal_size(fallback=(80, 24))
        viewport_height = max(5, term_rows - 5)
        self._scroll_offset = max(0, len(lines) - viewport_height)

    def _register_bindings(self):
        @self.kb.add("c-c")
        def _exit(event):
            event.app.exit()

        @self.kb.add("pageup")
        def _scroll_up(event):
            self._scroll_offset = max(0, self._scroll_offset - 6)
            event.app.invalidate()

        @self.kb.add("pagedown")
        def _scroll_down(event):
            self._scroll_offset += 6
            event.app.invalidate()

        @self.kb.add("escape", "up")
        def _alt_up(event):
            self._scroll_offset = max(0, self._scroll_offset - 3)
            event.app.invalidate()

        @self.kb.add("escape", "down")
        def _alt_down(event):
            self._scroll_offset += 3
            event.app.invalidate()

        @self.kb.add("enter")
        def _submit(event):
            # If the completions menu is open, Enter chooses the completion
            if self.input_buffer.complete_state:
                self.input_buffer.complete_state = None
                return

            text = self.input_buffer.text.strip()
            if not text:
                return
            if text.lower() in ("exit", "quit"):
                event.app.exit()
                return

            self.input_buffer.reset()

            expanded_text = self._expand_file_mentions(text)

            self.message_blocks.append(("user", text))
            self._scroll_to_bottom()
            event.app.invalidate()

            asyncio.create_task(self._process_turn(expanded_text))

    def _expand_file_mentions(self, text: str) -> str:
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
        if attachments:
            return text + "\n" + "".join(attachments)
        return text

    async def _process_turn(self, user_prompt: str):
        self.message_blocks.append(("thinking", ""))
        self._scroll_to_bottom()
        self.app.invalidate()

        self.history.append({"role": "user", "content": user_prompt})

        try:
            if asyncio.iscoroutinefunction(getattr(self.agent, "run", None)):
                response = await self.agent.run(self.history)
            else:
                response = await asyncio.to_thread(self.agent.run, self.history)

            if self.message_blocks and self.message_blocks[-1][0] == "thinking":
                self.message_blocks.pop()

            if response:
                self.history.append({"role": "assistant", "content": response})
                self.message_blocks.append(("agent", response))

        except Exception as e:
            if self.message_blocks and self.message_blocks[-1][0] == "thinking":
                self.message_blocks.pop()
            self.message_blocks.append(("error", str(e)))

        self._scroll_to_bottom()
        self.app.invalidate()

    def run(self):
        try:
            self.app.run()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass