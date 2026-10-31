import json
import os
from typing import List, Dict, Any
from groq import Groq
from app.config import settings
from app.tools import ToolRegistry

class CodingAgent():
    def __init__(self, registry: ToolRegistry):
        self._registry = registry
        self.client = Groq(api_key=settings.GROQ_API_KEY)


    def _load_memory(self) -> str:
        memory_path = os.path.join(settings.WORKSPACE_DIR, "AGENTS.md")

        if not os.path.exists(memory_path):
            return ""

        try:
            with open(memory_path, "r", encoding="utf-8") as f:
                memory_content = f.read()

            return str(memory_content)
        except(PermissionError, OSError, Exception):
            return ""
        

    def _build_system_prompt(self) -> str:
        memory = self._load_memory()

        system_prompt = "You are a senior level programmer, who can read, write, operate computer using terminal, and do much more, which is easier with the give tools and memory"

        structured_prompt = f"<system_prompt>{system_prompt} <memory> {memory} </memory></system_prompt>"

        return str(structured_prompt)

    def run(self, history: List[Dict[str, Any]]) -> str:

        messages = messages = [{"role": "system", "content": self._build_system_prompt()}] + list(history)

        iteration = 0

        while iteration <= settings.MAX_ITERATIONS:

            response = self.client.chat.completions.create(
                messages=messages,
                tools=self._registry.get_schemas(),
                tool_choice="auto",
                model=settings.MODEL_NAME
            )

            response_message = response.choices[0].message

            messages.append(response_message)

            if not response_message.tool_calls:
                return response_message.content

            for tool_call in response_message.tool_calls:
                tool_name= tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)

                result = self._registry.execute_tool(tool_name, tool_args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "name": tool_name,
                    "content": str(result)
                })


            iteration += 1

        return "Task incomplete: maximum iterations reached."


