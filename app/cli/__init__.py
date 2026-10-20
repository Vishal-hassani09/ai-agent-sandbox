import argparse
import os
import sys
from pathlib import Path

from app.cli.ui import AgentTerminalUI
from app.config import settings
from app.core.agent import CodingAgent
from app.tools import ToolRegistry
from app.tools.file_search import GlobTool
from app.tools.file_system import ReadFileTool, WriteFileTool
from app.tools.terminal import ShellTool


def parse_args():
    parser = argparse.ArgumentParser(
        description="Autonomous Coding Agent CLI",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-w",
        "--workspace",
        type=str,
        default=".",
        help="Path to the target project/workspace directory",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    workspace_path = Path(args.workspace).resolve()

    if not workspace_path.exists():
        print(f"Error: Target workspace directory does not exist: {workspace_path}", file=sys.stderr)
        sys.exit(1)

    # 1. Update config settings to target workspace
    settings.WORKSPACE_DIR = str(workspace_path)

    # 2. Change working directory so relative file globs and terminal tools stay bounded to workspace
    os.chdir(workspace_path)

    # 3. Setup tool registry scoped to workspace
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ShellTool())
    registry.register(GlobTool())

    # 4. Instantiate core agent
    agent = CodingAgent(registry)

    # 5. Launch UI
    ui = AgentTerminalUI(agent=agent, workspace_path=str(workspace_path))
    ui.run()


if __name__ == "__main__":
    main()