"""Module entrypoint (`python -m app.cli`) delegating directly to `app.cli.main`."""
from app.cli import main

if __name__ == "__main__":
    main()