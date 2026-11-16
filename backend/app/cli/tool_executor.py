"""Local execution engine that runs tool calls requested by the backend agent."""
import asyncio
import fnmatch
import os
from pathlib import Path
from typing import Any, Dict


class LocalToolExecutor:
    def __init__(self, workspace_path: str):
        self.workspace_path = Path(workspace_path).resolve()

    def _resolve_safe_path(self, rel_path: str) -> Path:
        target = (self.workspace_path / rel_path).resolve()
        if not str(target).startswith(str(self.workspace_path)):
            raise PermissionError(f"Access denied: path '{rel_path}' escapes workspace directory.")
        return target

    async def execute(self, tool_name: str, args: Dict[str, Any]) -> str:
        """Dispatches tool execution locally against the workspace."""
        clean = tool_name.lower().replace("_", "").replace("-", "").replace(".", "")

        # Write aliases
        if clean in ("writefile", "write", "createfile"):
            return await self.tool_write_file(args)

        # Edit / Patch aliases (surgical find & replace)
        if clean in ("editfile", "edit", "patch", "replaceinfile", "modifyfile"):
            return await self.tool_edit_file(args)

        # Read aliases
        if clean in ("readfile", "read", "viewfile", "cat"):
            return await self.tool_read_file(args)

        # Shell / Execution aliases
        if clean in ("shell", "terminal", "bash", "executecommand", "command", "exec", "containerexec", "repobrowserexec"):
            return await self.tool_shell(args)

        # Directory listing aliases
        if clean in ("listdirectory", "listdir", "listfiles", "ls", "dir"):
            return await self.tool_list_directory(args)

        # Glob / Search aliases
        if clean in ("glob", "globsearch", "globfiles", "find", "filesearch"):
            return await self.tool_glob(args)

        return f"Error: Tool '{tool_name}' not implemented on local daemon."

    async def tool_read_file(self, args: Dict[str, Any]) -> str:
        rel_path = args.get("path") or args.get("file_path") or args.get("filename")
        if not rel_path:
            return "Error: missing 'path' argument."
        file_path = self._resolve_safe_path(rel_path)
        if not file_path.is_file():
            return f"Error: File not found: {rel_path}"
        return file_path.read_text(encoding="utf-8", errors="replace")

    async def tool_write_file(self, args: Dict[str, Any]) -> str:
        rel_path = args.get("path") or args.get("file_path") or args.get("filename")
        content = args.get("content", "")
        if not rel_path:
            return "Error: missing 'path' argument."
        file_path = self._resolve_safe_path(rel_path)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        return f"Successfully wrote {len(content)} bytes to {rel_path}"

    async def tool_edit_file(self, args: Dict[str, Any]) -> str:
        """Surgically edits an existing file by replacing old_text with new_text."""
        rel_path = args.get("path") or args.get("file_path") or args.get("filename")
        old_text = args.get("old_text") or args.get("target") or args.get("find")
        new_text = args.get("new_text") if "new_text" in args else args.get("replace", "")

        if not rel_path:
            return "Error: missing 'path' argument."
        if old_text is None:
            return "Error: missing 'old_text' argument for find-and-replace."

        file_path = self._resolve_safe_path(rel_path)
        if not file_path.is_file():
            return f"Error: Target file not found: {rel_path}"

        current_content = file_path.read_text(encoding="utf-8", errors="replace")

        # Check for occurrence
        count = current_content.count(old_text)
        if count == 0:
            # Fallback check: ignore trailing whitespaces per line
            normalized_current = "\n".join(line.rstrip() for line in current_content.splitlines())
            normalized_old = "\n".join(line.rstrip() for line in old_text.splitlines())
            if normalized_old in normalized_current:
                current_content = normalized_current
                old_text = normalized_old
                count = 1
            else:
                return f"Error: The target 'old_text' was not found in {rel_path}. Make sure the code snippet matches exactly."

        if count > 1:
            return (
                f"Error: The target 'old_text' occurs {count} times in {rel_path}. "
                "Provide a larger unique context block so the replacement is unambiguous."
            )

        updated_content = current_content.replace(old_text, new_text, 1)
        file_path.write_text(updated_content, encoding="utf-8")
        return f"Successfully applied edit to {rel_path} (replaced 1 occurrence)."

    async def tool_list_directory(self, args: Dict[str, Any]) -> str:
        rel_path = args.get("path", "") or args.get("directory", "")
        dir_path = self._resolve_safe_path(rel_path) if rel_path else self.workspace_path
        if not dir_path.is_dir():
            return f"Error: Directory not found: {rel_path}"
        items = sorted(os.listdir(dir_path))
        return "\n".join(items) if items else "(empty directory)"

    async def tool_glob(self, args: Dict[str, Any]) -> str:
        pattern = args.get("pattern", "*")
        matched = []
        for root, _, files in os.walk(self.workspace_path):
            for f in files:
                rel = os.path.relpath(os.path.join(root, f), self.workspace_path)
                if fnmatch.fnmatch(rel, pattern):
                    matched.append(rel)
        return "\n".join(matched[:50]) if matched else f"No files matched pattern '{pattern}'."

    async def tool_shell(self, args: Dict[str, Any]) -> str:
        # Handles "command", "cmd", or cmd list ["bash", "-lc", "..."]
        raw_cmd = args.get("command") or args.get("cmd")
        if isinstance(raw_cmd, list):
            command = " ".join(raw_cmd)
        elif isinstance(raw_cmd, str):
            command = raw_cmd
        else:
            return "Error: missing 'command' argument."

        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(self.workspace_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60.0)
            output = stdout.decode("utf-8", errors="replace")
            err_output = stderr.decode("utf-8", errors="replace")
            if proc.returncode != 0:
                return f"Process failed (exit code {proc.returncode}):\n{err_output or output}"
            return output if output else "(Command executed with no output)"
        except asyncio.TimeoutError:
            proc.kill()
            return "Error: Shell command timed out after 60 seconds."