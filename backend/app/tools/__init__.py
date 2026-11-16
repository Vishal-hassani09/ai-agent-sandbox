from typing import Any, Dict, List
from app.tools.base import BaseTool
from app.tools.file_search import GlobTool
from app.tools.file_system import ListDirectoryTool, ReadFileTool, WriteFileTool, EditFileTool
from app.tools.terminal import ShellTool
from app.tools.ask_user import AskUserTool


class ToolRegistry:
    """
    Central dispatcher and registry for all available tools.
    Decouples the execution engine from concrete tool implementations.
    """
    def __init__(self):
        self._tools: Dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Registers a tool instance by its declared name."""
        if not isinstance(tool, BaseTool):
            raise TypeError(f"Tool {tool} must inherit from BaseTool")
        self._tools[tool.name] = tool

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Collects the JSON schemas of all registered tools for the LLM."""
        return [tool.get_schema() for tool in self._tools.values()]

    def execute_tool(self, name: str, arguments: Dict[str, Any]) -> str:
        """
        Locates the tool by name and executes it safely with error boundaries.
        """
        tool = self._tools.get(name)
        if not tool:
            return f"Error: Tool '{name}' is not registered."
        
        try:
            return tool.execute(**arguments)
        except Exception as e:
            return f"Execution Error in tool '{name}': {str(e)}"

def get_default_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(ReadFileTool())
    registry.register(WriteFileTool())
    registry.register(ListDirectoryTool())
    registry.register(ShellTool())
    registry.register(GlobTool())
    registry.register(EditFileTool())
    registry.register(AskUserTool())

    return registry