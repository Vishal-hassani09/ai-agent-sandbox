"""CLI entry point for the Autonomous Coding Agent (supports Terminal CLI and Render Web UI modes)."""
import argparse
import os
import sys
from pathlib import Path

from app.cli.auth_manager import login_or_register_cli
from app.cli.client import AssistantAPIClient
from app.cli.daemon import start_ui_daemon
from app.cli.ui import AgentTerminalUI


def main():
    parser = argparse.ArgumentParser(
        prog="ai-coder",
        description="Autonomous Coding Agent — Terminal CLI & Render Web UI Device Bridge",
    )
    parser.add_argument(
        "mode",
        nargs="?",
        choices=["cli", "ui"],
        default=None,
        help="Launch mode: 'cli' for terminal interface, 'ui' to connect local device to Render Web UI.",
    )
    parser.add_argument(
        "--ui",
        action="store_true",
        help="Shortcut flag to launch the local device bridge and open the Render Web UI.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not automatically open the browser when starting in UI bridge mode.",
    )
    args = parser.parse_args()

    try:
        # 1. Resolve active working directory on user's machine
        workspace = str(Path(os.getcwd()).resolve())

        # 2. Determine preferred interface mode (CLI vs Web UI)
        selected_mode = "ui" if args.ui else args.mode
        if selected_mode is None:
            print("\nSelect interface mode:")
            print("  [1] Terminal CLI  (Interactive coding directly in this terminal)")
            print("  [2] Web Studio UI (Open Render Web UI connected to your local device)")
            choice = input("Enter choice [1/2] (default: 1): ").strip().lower()
            selected_mode = "ui" if choice in ("2", "ui", "web") else "cli"

        # 3A. Web UI Mode: start device bridge immediately (login happens ONLY on the Web UI)
        if selected_mode == "ui":
            start_ui_daemon(
                workspace_path=workspace,
                open_browser=not args.no_browser,
            )
            return

        # 3B. Terminal CLI Mode: authenticate in terminal and run TUI
        token = login_or_register_cli()
        client = AssistantAPIClient(token)

        sessions = client.list_sessions_for_workspace(workspace)
        if not sessions:
            folder_name = Path(workspace).name or "Root"
            new_sess = client.create_session(workspace, f"Session in {folder_name}")
            sessions = [new_sess]

        ui = AgentTerminalUI(
            api_client=client,
            workspace_path=workspace,
            initial_sessions=sessions,
        )
        ui.run()

    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as e:
        print(f"\n[CLI Error] {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()