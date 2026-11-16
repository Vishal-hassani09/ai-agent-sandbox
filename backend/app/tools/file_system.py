import os
from pathlib import Path
from typing import Dict, Any, Optional
from app.config import settings
from app.tools.base import BaseTool
from app.utils.common_utils import get_safe_path


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read the contents of a file in the workspace. Provide 'filename' (or 'path')."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Relative path or name of the file to read (e.g. 'AGENTS.md').",
                        },
                        "path": {
                            "type": "string",
                            "description": "Alias for filename: relative path of the file to read.",
                        },
                    },
                    "required": [],
                },
            },
        }

    def execute(self, filename: Optional[str] = None, path: Optional[str] = None, **kwargs: Any) -> str:
        target = filename or path or kwargs.get("file_path")
        if not target:
            return "Error: Please provide 'filename' (or 'path') to read_file."
        try:
            safe_path = get_safe_path(target)
            if not os.path.exists(safe_path):
                raise FileNotFoundError(f"File '{target}' does not exist.")

            with open(safe_path, "r", encoding="utf-8") as f:
                file_content = f.read()

            return file_content if file_content else "File is empty"
        except (PermissionError, FileNotFoundError) as err:
            return f"Error: {str(err)}"


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Create or overwrite a file in the workspace. Provide 'filename' (or 'path') and 'content'."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filename": {
                            "type": "string",
                            "description": "Relative path or name of the file to write (e.g. 'AGENTS.md').",
                        },
                        "path": {
                            "type": "string",
                            "description": "Alias for filename: relative path of the file to write.",
                        },
                        "content": {
                            "type": "string",
                            "description": "The full text content to write into the file.",
                        },
                    },
                    "required": [],
                },
            },
        }

    def execute(
        self,
        filename: Optional[str] = None,
        content: str = "",
        path: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = filename or path or kwargs.get("file_path")
        if not target:
            return "Error: Please provide 'filename' (or 'path') to write_file."
        try:
            safe_path = get_safe_path(target)
            parent_dir = os.path.dirname(safe_path)

            if parent_dir:
                os.makedirs(parent_dir, exist_ok=True)

            with open(safe_path, mode="w", encoding="utf-8") as f:
                f.write(content)

            return f"Success: File '{target}' written successfully ({len(content)} characters)."

        except PermissionError as err:
            return f"Error: {str(err)}"


class ListDirectoryTool(BaseTool):
    name = "list_files"
    description = "List files and directories inside the workspace (or an optional subdirectory 'path')."

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Optional relative directory path (leave empty for workspace root).",
                        },
                        "directory": {
                            "type": "string",
                            "description": "Optional alias for path.",
                        },
                    },
                    "required": [],
                },
            },
        }

    def execute(self, path: str = "", directory: str = "", **kwargs: Any) -> str:
        try:
            workspace = os.path.abspath(settings.WORKSPACE_DIR)
            os.makedirs(workspace, exist_ok=True)
            rel = path or directory
            target_dir = get_safe_path(rel) if rel else workspace
            files = os.listdir(target_dir)
            if not files:
                return "Workspace is empty."

            return "\n".join(f"- {f}" for f in sorted(files))

        except Exception as err:
            return f"Error: {str(err)}"


class EditFileTool(BaseTool):
    name = "edit_file"
    description = (
        "Surgically modifies an existing file by replacing an exact snippet 'old_text' "
        "with 'new_text'. Use this instead of write_file for modifying existing code."
    )

    def get_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Relative path of the existing file to edit.",
                        },
                        "filename": {
                            "type": "string",
                            "description": "Alias for path: relative path of the existing file to edit.",
                        },
                        "old_text": {
                            "type": "string",
                            "description": "The exact existing text block or lines to find and replace.",
                        },
                        "new_text": {
                            "type": "string",
                            "description": "The replacement text block or lines.",
                        },
                    },
                    "required": [],
                },
            },
        }

    def execute(
        self,
        path: Optional[str] = None,
        old_text: str = "",
        new_text: str = "",
        filename: Optional[str] = None,
        **kwargs: Any,
    ) -> str:
        target = path or filename or kwargs.get("file_path")
        if not target:
            return "Error: Please provide 'path' (or 'filename') to edit_file."
        file_path = Path(target)
        if not file_path.is_file():
            return f"Error: Target file not found: {target}"
        content = file_path.read_text(encoding="utf-8", errors="replace")
        if old_text not in content:
            return f"Error: The target 'old_text' was not found in {target}."
        if content.count(old_text) > 1:
            return f"Error: 'old_text' occurs multiple times in {target}. Provide more surrounding lines."
        updated = content.replace(old_text, new_text, 1)
        file_path.write_text(updated, encoding="utf-8")
        return f"Successfully applied edit to {target}."