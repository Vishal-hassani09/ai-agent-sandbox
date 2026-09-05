import os
import subprocess
from typing import Dict, Any
from app.config import settings
from app.tools.base import BaseTool


class ShellTool(BaseTool):
    name = "execute_command"
    description = "Executes a shell command inside the workspace directory and returns stdout, stderr, and exit code."


    def get_schema(self) -> Dict[str, Any]:
        tool_schema = {
                    "type": "function",
                    "function": {
                        "name": self.name,
                        "description": self.description,
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "command": {"type": "string", 'description':"Command that is to be executed" }
                            },
                            "required": ["command"]
                        }
                    }
                }
        
        return tool_schema


    def execute(self, command: str) -> str:
        try:
            workspace = os.path.abspath(settings.WORKSPACE_DIR)
            os.makedirs(workspace, exist_ok=True)
            process = subprocess.run(command, shell=True, capture_output=True, timeout=60, text=True, cwd=workspace)
            try:
                return f"Returncode: {process.returncode}, Output: {process.stdout.strip()}, Error: {process.stderr.strip()}"
            except Exception as err:
                return f"Error while assembling the output: {err}"
            
        except subprocess.TimeoutExpired as err:
            return f"Error: {str(err)}"
        except Exception as err:
            return f"Error: {str(err)}"