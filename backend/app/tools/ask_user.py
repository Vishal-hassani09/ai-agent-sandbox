"""Tool allowing the agent to ask structured clarifying questions with interactive options."""
from typing import Any, Dict, List
from app.tools.base import BaseTool


class AskUserTool(BaseTool):
    name = "ask_user"
    description = (
        "Ask the user 1 or more structured clarifying questions with selectable options. "
        "The CLI renders an interactive selector with ↑/↓ option navigation, ←/→ tab switching, "
        "and an automatic custom text input option at the end."
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
                        "questions": {
                            "type": "array",
                            "description": "List of questions to present to the user.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "header": {
                                        "type": "string",
                                        "description": "Short tab label (e.g., 'Framework', 'Auth Method').",
                                    },
                                    "question": {
                                        "type": "string",
                                        "description": "The full question to display.",
                                    },
                                    "options": {
                                        "type": "array",
                                        "description": "2 to 4 concise choices (do not include 'Other', it is added automatically).",
                                        "items": {"type": "string"},
                                    },
                                },
                                "required": ["header", "question", "options"],
                            },
                        }
                    },
                    "required": ["questions"],
                },
            },
        }

    def execute(self, questions: List[Dict[str, Any]]) -> str:
        # Intercepted and executed interactively on the local CLI daemon
        return "Handled interactively by CLI client."