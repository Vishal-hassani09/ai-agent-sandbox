import os
from app.config import settings
from app.tools.base import BaseTool
from typing import Dict, Any
from app.utils.common_utils import get_safe_path


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "It is used to read the contents of the file"

    def get_schema(self) -> Dict[str, Any]:
        tool_schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", 'description':"Name of the file to be read" }
                    },
                    "required": ["filename"]
                }
            }
        }

        return tool_schema

    def execute(self, filename: str) -> str:
        try:
            safe_path=get_safe_path(filename)
            if not os.path.exists(safe_path):
                raise FileNotFoundError(f"File '{filename}' does not exist.")

            with open(safe_path, 'r', encoding="utf-8") as f:
                file_content = f.read()

            if not file_content:
                return "File is empty"
            else:
                return file_content
        except (PermissionError, FileNotFoundError) as err:
            return f"Error: {str(err)}"


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "It is used to write the contents in the file"

    def get_schema(self) -> Dict[str, Any]:
        tool_schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {"type": "string", 'description':"Name of the file to be written" },
                        "content": {"type": "string", "description": "The content of the file that will be written"}
                    },
                    "required": ["filename", "content"]
                }
            }
        }

        return tool_schema

    def execute(self, filename: str, content: str) -> str:
        try:
            safe_path=get_safe_path(filename)
            parent_dir= os.path.dirname(safe_path)

            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with open(safe_path, mode='w' , encoding="utf-8") as f:
                f.write(content)

            return f"Success: File '{filename}' written successfully ({len(content)} characters)."

        except (PermissionError) as err:
            return f"Error: {str(err)}"


class ListDirectoryTool(BaseTool):
    name = "list_files"
    description = "It is used to list the directories"

    def get_schema(self) -> Dict[str, Any]:
        tool_schema = {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        }

        return tool_schema

    def execute(self) -> str:
        try:
            workspace = os.path.abspath(settings.WORKSPACE_DIR)
            os.makedirs(workspace, exist_ok=True)
            files=os.listdir(workspace)
            if not files:
                return "Workspace is empty."

            return "\n".join(f"- {f}" for f in sorted(files))

        except Exception as err:
            return f"Error: {str(err)}"