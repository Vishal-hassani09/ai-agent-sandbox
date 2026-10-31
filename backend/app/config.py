import os
from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = PROJECT_ROOT / ".env"

class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables and .env file.
    Validates types and fails immediately on startup if required variables are missing.
    """
    # Required setting - app will not boot if this is missing from .env
    GROQ_API_KEY: str

    # Optional defaults with strong types
    MODEL_NAME: str = "openai/gpt-oss-120b"
    MAX_ITERATIONS: int = 8
    WORKSPACE_DIR: str = os.getcwd() or "./workspace"

    # Configuration to instruct Pydantic to read from a local .env file
    model_config = SettingsConfigDict(
        env_file= ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore"  # Ignore extra unrelated env variables safely
    )


# Singleton instance to be imported across modules
settings = Settings()