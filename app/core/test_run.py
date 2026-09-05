from app.tools import get_default_registry
from app.core.agent import CodingAgent

def test():
    registry = get_default_registry()
    agent = CodingAgent(registry=registry)

    prompt = (
        "1. Write a python file 'calculator.py' with a function 'multiply(a, b)'\n"
        "2. Run a command using execute_command to test that 'multiply(6, 7)' prints 42\n"
        "3. Confirm the result."
    )

    print("Running Agent...")
    response = agent.run([{"role": "user", "content": prompt}])
    print("\n--- Final Output ---")
    print(response)

if __name__ == "__main__":
    test()