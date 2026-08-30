import json
import os
import requests
from dotenv import load_dotenv
from groq import Groq

# ==============================================================================
# 1. INITIALIZATION & SECRETS
# ==============================================================================
load_dotenv()
client = Groq()
MODEL_NAME = "openai/gpt-oss-120b"

# ==============================================================================
# 2. TOOL DEFINITIONS
# ==============================================================================
def calculate_sum(a: float, b: float) -> str:
    """Calculates the sum of two numbers."""
    return str(a + b)

def calculate_product(a: float, b: float) -> str:
    """Multiplies two numbers."""
    return str(a * b)

def get_crypto_price(coin: str) -> str:
    """Fetches real-time cryptocurrency prices in USD via CoinGecko API."""
    try:
        url = f"https://api.coingecko.com/api/v3/simple/price?ids={coin.lower()}&vs_currencies=usd"
        res = requests.get(url, timeout=5).json()
        if coin.lower() in res:
            price = res[coin.lower()]["usd"]
            return f"{price}"
        return f"Error: Coin '{coin}' not found."
    except Exception as e:
        return f"API Error: {str(e)}"

# Registry mapping tool names to callable Python functions
available_tools = {
    "calculate_sum": calculate_sum,
    "calculate_product": calculate_product,
    "get_crypto_price": get_crypto_price,
}

# ==============================================================================
# 3. TOOL SCHEMAS
# ==============================================================================
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
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_product",
            "description": "Multiplies two numbers together.",
            "parameters": {
                "type": "object",
                "properties": {
                    "a": {"type": "number", "description": "First factor"},
                    "b": {"type": "number", "description": "Second factor"},
                },
                "required": ["a", "b"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_crypto_price",
            "description": "Fetches current market price in USD for a given cryptocurrency (e.g., 'bitcoin', 'ethereum', 'solana').",
            "parameters": {
                "type": "object",
                "properties": {
                    "coin": {"type": "string", "description": "Cryptocurrency ID (lowercase)"},
                },
                "required": ["coin"],
            },
        },
    },
]

# ==============================================================================
# 4. RECURSIVE AGENT ENGINE
# ==============================================================================
def run_agent_loop(messages: list) -> str:
    """
    Autonomous Execution Engine:
    Keeps calling tools sequentially until the model produces a final text reply.
    """
    iteration = 1
    MAX_ITERATIONS = 5  # Guardrail: prevents infinite loops if the model gets stuck

    while iteration <= MAX_ITERATIONS:
        print(f"\n[Agent Step {iteration}] Calling model...")
        
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        response_message = response.choices[0].message
        messages.append(response_message)

        # If the LLM didn't request any tools, it has reached a final natural-language response
        if not response_message.tool_calls:
            return response_message.content

        # Process each tool call emitted in this turn
        for tool_call in response_message.tool_calls:
            func_name = tool_call.function.name
            func_args = json.loads(tool_call.function.arguments)

            print(f"⚙️  [Executing Tool]: {func_name} with arguments {func_args}")

            # Safe lookup in the registry hash table
            if func_name in available_tools:
                try:
                    tool_output = available_tools[func_name](**func_args)
                except Exception as err:
                    tool_output = f"Execution Error: {str(err)}"
            else:
                tool_output = f"Error: Tool '{func_name}' is not registered."

            print(f"📥 [Tool Result]: {tool_output}")

            # Append the tool's result to conversation history
            messages.append({
                "tool_call_id": tool_call.id,
                "role": "tool",
                "name": func_name,
                "content": str(tool_output),
            })

        iteration += 1

    return "Agent reached maximum iteration limit without resolving."

# ==============================================================================
# 5. INTERACTIVE CLI CHAT
# ==============================================================================
if __name__ == "__main__":
    chat_history = [
        {"role": "system", "content": "You are a helpful, precise AI assistant with access to real-time calculation and data tools."}
    ]

    print("==================================================")
    print(" Agent Ready (Type 'exit' or 'quit' to stop)")
    print("==================================================\n")

    while True:
        user_text = input("You: ").strip()
        if not user_text:
            continue
        if user_text.lower() in ["exit", "quit"]:
            print("Session ended.")
            break

        chat_history.append({"role": "user", "content": user_text})
        reply = run_agent_loop(chat_history)
        print(f"\nAgent: {reply}\n")