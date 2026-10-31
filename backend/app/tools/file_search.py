from pathlib import Path
from typing import Dict, Any
from app.config import settings
from app.tools.base import BaseTool

class GlobTool(BaseTool):
    name = "glob_files"
    description =  "Search for files matching a glob pattern (e.g., '**/*.py', 'src/*.ts') inside the workspace."

    def get_schema(self) -> Dict[str, Any]:
        tool_schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "The glob pattern to search for (e.g. '**/*.py')"}
                    },
                    "required": ["pattern"]
                }
            }
        }
    
        return tool_schema


    def execute(self, pattern: str) -> str:
        matched_files = []
        try:
            ignored =  {".git", ".venv", "__pycache__", "node_modules"}
            root = Path(settings.WORKSPACE_DIR).resolve()

            if not root.exists() :
                return "Workspace directory does not exist."

            for p in root.glob(pattern):
                if not p.is_file():
                    continue

                if any(part in ignored for part in p.parts):
                    continue

                matched_files.append(str(p.relative_to(root)))

            if not matched_files:
                return f"No matching files found with {pattern}"

            return "\n".join(matched_files)

        except Exception as err:
            return f"Error fetching files: {err}"