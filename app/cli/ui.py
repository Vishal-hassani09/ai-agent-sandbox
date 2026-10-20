from pathlib import Path
import shutil
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.formatted_text import HTML
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from prompt_toolkit.filters import completion_is_selected, has_completions
from prompt_toolkit.key_binding import KeyBindings

console = Console()


class WorkspaceFileCompleter(Completer):

    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if "@" not in text:
            return

        prefix = text.split("@")[-1]
        try:
            for file_path in self.workspace_dir.rglob("*"):
                if file_path.is_file() and not any(
                    p.startswith(".") for p in file_path.parts
                ):
                    rel = str(
                        file_path.relative_to(self.workspace_dir)
                    ).replace("\\", "/")
                    if rel.lower().startswith(prefix.lower()):
                        yield Completion(
                            text=f"@{rel} ",
                            start_position=-len(prefix) - 1,
                            display=f"@{rel}",
                        )
        except Exception:
            pass


def create_prompt_session(workspace_dir: str) -> PromptSession:
    kb = KeyBindings()

    # Pressing Tab applies the currently selected completion immediately
    @kb.add("tab", filter=completion_is_selected)
    def _apply_on_tab(event):
        buff = event.current_buffer
        if buff.complete_state and buff.complete_state.current_completion:
            buff.apply_completion(buff.complete_state.current_completion)
            buff.complete_state = None

    # Pressing Enter while the completion menu is open accepts it without submitting the prompt
    @kb.add("enter", filter=has_completions)
    def _accept_on_enter(event):
        buff = event.current_buffer
        if buff.complete_state and buff.complete_state.current_completion:
            buff.apply_completion(buff.complete_state.current_completion)
            buff.complete_state = None

    return PromptSession(
        completer=WorkspaceFileCompleter(workspace_dir),
        key_bindings=kb,
        complete_while_typing=True,
    )


def get_input_prompt_header():
    width = shutil.get_terminal_size().columns
    line_len = max(0, width - 11)
    return HTML(f"<ansicyan>╭─ <b>Input</b> {'─' * line_len}╮\n│ </ansicyan>")


def print_prompt_box_footer():
    width = shutil.get_terminal_size().columns
    line_len = max(0, width - 2)
    console.print(f"[cyan]╰{'─' * line_len}╯[/cyan]")


def print_banner(workspace_dir: str):
    console.print(
        Panel(
            f"[bold green]Autonomous Coding Agent[/bold green]\n"
            f"[cyan]Workspace:[/cyan] {workspace_dir}\n"
            f"[dim]Type @filename (press Tab) to attach files | Type 'exit' to quit[/dim]",
            border_style="cyan",
        )
    )


def print_user_prompt(user_prompt: str):
    console.print(f"\n[bold cyan]User:[/bold cyan] {user_prompt}\n")


def print_assistant_response(response: str):
    console.print(Markdown(response))
    console.print()


def get_status_spinner(text: str):
    return console.status(text, spinner="dots")


def print_exit_banner():
    console.print("\n[yellow]Goodbye![/yellow]")