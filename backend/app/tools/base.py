from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseTool(ABC):
    """
    Abstract Base Class that every tool must inherit from.
    Enforces a strict contract for tool schemas and execution.
    """
    name: str
    description: str

    @abstractmethod
    def get_schema(self) -> Dict[str, Any]:
        """
        Returns the OpenAI/Groq-compatible JSON schema definition for the tool.
        """
        pass

    @abstractmethod
    def execute(self, **kwargs) -> str:
        """
        Executes the business logic of the tool with the provided arguments.
        Must return a string representation of the output or error.
        """
        pass