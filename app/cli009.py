import os, sys, argparse
from app.config import settings
from app.core.agent import CodingAgent
from app.tools import get_default_registry
from app.cli.ui import console, print_banner, print_assistant_response, get_status_spinner

def parse_args():
    parser = argparse.ArgumentParser( description="Autonomous Coding Assistant CLI")
    parser.add_argument("--workspace","-w",type=str, default=os.getcwd(), help="Target workspace directory (defaults to current working directory)")

    return parser.parse_args()

def main():

    # Resolving workspace
    args = parse_args()
    workspace_path = os.path.abspath(args.workspace)
    os.makedirs(workspace_path, exist_ok=True)
    settings.WORKSPACE_DIR = workspace_path

    # Initialisation
    registry = get_default_registry()
    agent = CodingAgent(registry=registry)
    history = []


    print_banner(settings.WORKSPACE_DIR)


    while True:
        try:
            user_prompt = input("\nYou:> ").strip()

            if not user_prompt:
                continue
            if user_prompt.lower() in ["quit", "exit", "q"]:
                print("\nSession Ended")
                break

            history.append({"role": "user", "content":user_prompt})

            with get_status_spinner("[bold cyan]Thinking & executing tools...[/bold cyan]"):
                response = agent.run(history)

            print_assistant_response(response)

            history.append({"role": "assistant", "content": response})

        except (KeyboardInterrupt, EOFError) as err:
            print("\nSession Ended")
            break


if __name__== "__main__" : main()









