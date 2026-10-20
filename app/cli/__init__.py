import argparse
import os
from pathlib import Path
import shutil
import sys
from app.cli.ui import (
    console,
    create_prompt_session,
    get_input_prompt_header,
    get_status_spinner,
    print_assistant_response,
    print_banner,
    print_exit_banner,
    print_prompt_box_footer,
    print_user_prompt,
)
from app.config import settings
from app.core.agent import CodingAgent
from app.tools import get_default_registry
from app.utils.prompt_expander import expand_file_mentions


def main() -> None:
    parser = argparse.ArgumentParser(description="Autonomous Coding Agent")
    parser.add_argument(
        "-w",
        "--workspace",
        type=str,
        default=settings.WORKSPACE_DIR,
        help="Target workspace directory",
    )
    args = parser.parse_args()

    # Workspace directory sync
    workspace_dir = str(Path(args.workspace).resolve())
    settings.WORKSPACE_DIR = workspace_dir
    os.chdir(workspace_dir)

    registry = get_default_registry()
    agent = CodingAgent(registry=registry)

    print_banner(workspace_dir)
    session = create_prompt_session(workspace_dir)
    history = []

    while True:
        try:
            user_prompt = session.prompt(get_input_prompt_header).strip()
            print_prompt_box_footer()

            if not user_prompt:
                continue

            if user_prompt.lower() in ["quit", "exit", "q"]:
                print_exit_banner()
                break

            enriched_prompt = expand_file_mentions(user_prompt, workspace_dir)
            history.append({"role": "user", "content": enriched_prompt})

            with get_status_spinner(
                "[bold cyan]Thinking & executing...[/bold cyan]"
            ):
                response = agent.run(history)

            print_assistant_response(response)
            history.append({"role": "assistant", "content": response})

        except (KeyboardInterrupt, EOFError):
            print_exit_banner()
            sys.exit(0)


if __name__ == "__main__":
    main()