import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict


PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
ENV_FILE_PATH = PROJECT_ROOT / ".env"


class Settings(BaseSettings):
    """
    Application configuration loaded from environment variables and .env file.
    Validates types and fails immediately on startup if required variables are missing.
    """
    # Required settings
    GROQ_API_KEY: str
    DATABASE_URL: str

    SECRET_KEY: Optional[str] = None
    JWT_SECRET_KEY: Optional[str] = None

    # Optional LLM & workspace settings
    MODEL_NAME: str = "qwen/qwen3.8-27b"
    MAX_ITERATIONS: int = 8
    WORKSPACE_DIR: str = os.getcwd() or "./workspace"

    # Optional SMTP Email Settings for OTP delivery (falls back to console log in local dev)
    SMTP_HOST: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SMTP_FROM_EMAIL: Optional[str] = None

    model_config = SettingsConfigDict(
        env_file=ENV_FILE_PATH,
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()