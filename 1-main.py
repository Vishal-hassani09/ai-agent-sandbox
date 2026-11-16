"""Lists all models enabled for your GROQ_API_KEY."""
import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

def list_models():
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        print("Error: GROQ_API_KEY not found in environment or .env file.")
        return

    client = Groq(api_key=api_key)
    models = client.models.list()

    print(f"{'MODEL ID':<42} {'OWNER':<18} {'CONTEXT WINDOW'}")
    print("-" * 78)
    for m in sorted(models.data, key=lambda x: x.id):
        ctx = getattr(m, "context_window", "N/A")
        owner = getattr(m, "owned_by", "N/A")
        print(f"{m.id:<42} {owner:<18} {ctx}")

if __name__ == "__main__":
    list_models()