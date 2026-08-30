import json
import os
from dotenv import load_dotenv
from groq import Groq
import requests

load_dotenv()
client = Groq()
MODEL_NAME = "openai/gpt-oss-120b"

# print(f"client: {client.models.list()}")
# print(f"model_name: {MODEL_NAME}")

# tools definition

def weather_tool(latitude: float, longitude: float, date: str) -> str:
    """
    Fetches the average daily temperature for a specific location and date.
    
    :param latitude: Latitude of the location (e.g., 19.0760)
    :param longitude: Longitude of the location (e.g., 72.8777)
    :param date: Date in 'YYYY-MM-DD' format (e.g., '2024-05-15')
    :return: JSON string containing the date and average temperature in °C
    """

    url = "https://archive-api.open-meteo.com/v1/archive"
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": date,
        "end_date": date,
        "daily": "temperature_2m_mean",
        "timezone": "auto"
    }

    try:
        response = requests.get(url, params, timeout=5)
        response.raise_for_status()
        data = response.json()

        daily_data = data.get("daily", {})
        avg_temp = daily_data.get("temperature_2m_mean", [None])[0]

        return json.dumps({
            "date": date,
            "latitude": latitude,
            "longitude": longitude,
            "average_temperature_celsius": avg_temp,
            "unit": "°C"
        })
    except Exception as e:
        return json.dumps({"error": str(e)})

def calculate_sum(a: float, b: float) -> str:
    """ Calculates the sum of two numbers"""
    return str(a + b)


# tools mapping

available_tools = {
    'addition': calculate_sum,
    'get_weather': weather_tool
}

# tools schema

tools = [
    {
        "type": "function",
        "function":{ 
            "name":"addition",
            "description": "Calculates the sum of two numbers.",
            "parameters": {
                "type": "object",
                "properties":{
                    "a": {"type": "number", "description": "First number"},
                    "b": {"type": "number", "description": "Second number"}
                },
                "required": ["a", "b"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Fetch historical daily average temperature for a specific coordinate and date.",
            "parameters": {
                "type": "object",
                "properties": {
                    "latitude": {
                        "type": "number",
                        "description": "Latitude coordinate of the city/location in float not string."
                    },
                    "longitude": {
                        "type": "number",
                        "description": "Longitude coordinate of the city/location in float not string."
                    },
                    "date": {
                        "type": "string",
                        "description": "The target date in 'YYYY-MM-DD' format."
                    }
                },
                "required": ["latitude", "longitude", "date"]
            }
        }
    }
]

def run_agent_loop(messages: list) -> str:
    """
    Autonomous Execution Engine:
    Keeps calling tools sequentially until the model produces a final text reply.
    """

    iteration = 0
    MAX_ITERATIONS = 2

    while iteration < MAX_ITERATIONS:
        model_response = client.chat.completions.create(
            tools=tools,
            messages=messages,
            model=MODEL_NAME,
            tool_choice="auto"
        )

        response_message = model_response.choices[0].message
        messages.append(response_message)

        if not response_message.tool_calls:
            return json.dumps({"role": "assistant", "content": response_message.content})


        for tool_call in response_message.tool_calls:
            tool_name = tool_call.function.name
            tool_arg = json.loads(tool_call.function.arguments)

            if tool_name in available_tools:
                try:
                    tool_output = available_tools[tool_name](**tool_arg)
                except Exception as err:
                    tool_output = f"Execution Error: {str(err)}"
            else:
                tool_output = f"Error: Tool '{tool_name}' is not registered."

            messages.append({
                "role": "tool",
                "name": tool_name,
                "tool_call_id": tool_call.id,
                "content": str(tool_output)
            })

        iteration += 1

    return json.dumps({"role": "system", "content":"Agent reached maximum iteration limit without resolving."})

# def call_model(messages: list) -> str:
    """
    Calls the model with the given messages and returns the response.
    """

    model_response = client.chat.completions.create(
        messages=messages,
        model=MODEL_NAME
    )

    return model_response.choices[0].message.content



if __name__ == "__main__":
    chat_messages = [{
        "role": "system",
        "content": "You are a conversational AI assistant with appropriate tools. If user says anything that looks like they want to exit the chat only respond 'exit'."
    }]

    # print(call_model.__doc__) to fetch the description of the function

    print("==================================================")
    print(" Agent Ready (Type 'exit' or 'quit' to stop)")
    print("==================================================\n")

    while True:
        user_prompt =  input("User: ")
        if not user_prompt:
            continue

        chat_messages.append({"role": "user", "content": user_prompt})
        reply = json.loads(run_agent_loop(chat_messages))

        if reply["content"] == "exit":
            break

        chat_messages.append(reply)
        print(f"Model:  {reply["content"]}")
