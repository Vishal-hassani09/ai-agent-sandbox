import os
import subprocess
from typing import Dict, Any, Optional
from app.config import settings
from app.tools.base import BaseTool


class ShellTool(BaseTool):
    name = "execute_command"
    description = "Executes a shell command inside the workspace directory and returns stdout, stderr, and exit code."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to execute inside the workspace.",
                        },
                        "cmd": {
                            "type": "string",
                            "description": "Alias for command.",
                        },
                    },
                    "required": [],
                },
            },
        }

    def execute(self, command: Optional[str] = None, cmd: Optional[str] = None, **kwargs: Any) -> str:
        target_cmd = command or cmd
        if not target_cmd:
            return "Error: Please provide a non-empty 'command' string to execute_command."
        try:
            workspace = os.path.abspath(settings.WORKSPACE_DIR)
            os.makedirs(workspace, exist_ok=True)
            process = subprocess.run(
                target_cmd,
                shell=True,
                capture_output=True,
                timeout=60,
                text=True,
                cwd=workspace,
                check=False,
            )
            try:
                return f"Returncode: {process.returncode}, Output: {process.stdout.strip()}, Error: {process.stderr.strip()}"
            except Exception as err:
                return f"Error while assembling the output: {err}"

        except subprocess.TimeoutExpired as err:
            return f"Error: {str(err)}"
        except Exception as err:
            return f"Error: {str(err)}"