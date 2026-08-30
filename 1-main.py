import json
import os
from dotenv import load_dotenv
from groq import Groq

# ==========================================
# STEP 1: INITIALIZATION
# ==========================================
load_dotenv()
client = Groq()

# You can use "openai/gpt-oss-120b" or "llama-3.1-8b-instant"
MODEL_NAME = "openai/gpt-oss-120b"

# Define Python tool
def calculate_sum(a: float, b: float) -> str:
    return str(a + b)

available_tools = {
    "calculate_sum": calculate_sum
}

tools = [
    {
        "type": "function",
        "function": {
            "name": "calculate_sum",
            "description": "Calculates the sum of two numbers.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"},
                },
                "required": ["a", "b"],
            },
        },
    }
]

# ==========================================
# STEP 2: USER INPUT & INITIAL PROMPT
# ==========================================
user_prompt = "Can you add 48291 and 93821 for me?"
messages = [{"role": "user", "content": user_prompt}]

print("\n==================== STEP 1: SENDING USER PROMPT TO LLM ====================")
print(f"[INPUT TO LLM]:\nMessages: {json.dumps(messages, indent=2)}")
print(f"Tools Provided: {json.dumps(tools, indent=2)}")

# ==========================================
# STEP 3: FIRST LLM CALL (DECISION)
# ==========================================
response = client.chat.completions.create(
    model=MODEL_NAME,
    messages=messages,
    tools=tools,
    tool_choice="auto",
)

response_message = response.choices[0].message
tool_calls = response_message.tool_calls

print("\n==================== STEP 2: LLM RESPONSE (TOOL SELECTION) ====================")

if tool_calls:
    print(f"[Output from LLM whole response]: {response_message.content}")
    print(f"[Output from LLM whole tool_calls]: {json.dumps([tool_call.model_dump() for tool_call in tool_calls], indent=2)}")
    for tool_call in tool_calls:
        print(f"[OUTPUT FROM LLM]: Model decided to call function: '{tool_call.function.name}'")
        print(f"Tool Call ID: {tool_call.id}")
        print(f"Extracted Arguments (Raw JSON String): {tool_call.function.arguments}")
else:
    print("[OUTPUT FROM LLM]: No tool required. Plain text generated.")
    print(response_message.content)
    exit()

# ==========================================
# STEP 4: LOCAL EXECUTION (YOUR MACHINE)
# ==========================================
print("\n==================== STEP 3: LOCAL TOOL EXECUTION ====================")
messages.append(response_message)

for tool_call in tool_calls:
    func_name = tool_call.function.name
    func_args = json.loads(tool_call.function.arguments)
    
    print(f"[INPUT TO LOCAL PYTHON FUNCTION]: Calling {func_name}(**{func_args})")
    
    # Execute function
    tool_output = available_tools[func_name](**func_args) 
    
    print(f"[OUTPUT FROM LOCAL PYTHON FUNCTION]: Returned '{tool_output}'")

    # Append result back
    messages.append({
        "tool_call_id": tool_call.id,
        "role": "tool",
        "name": func_name,
        "content": tool_output,
    })

# ==========================================
# STEP 5: FINAL SYNTHESIS CALL
# ==========================================
print("\n==================== STEP 4: SENDING EXECUTION RESULT TO LLM ====================")
print(f"[INPUT TO LLM (Full Conversation History)]:\n{json.dumps(messages, indent=2, default=lambda o: o.__dict__)}")

final_response = client.chat.completions.create(
    model=MODEL_NAME,
    messages=messages
)

final_message = final_response.choices[0].message.content

print("\n==================== STEP 5: FINAL NATURAL ANSWER ====================")
print(f"[FINAL OUTPUT TO USER]:\n{final_message}\n")