import os
from pathlib import Path
from typing import List, Optional
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Telegram Settings
    TELEGRAM_BOT_TOKEN: str = Field(
        default="",
        description="Telegram Bot token obtained from BotFather"
    )
    ALLOWED_TELEGRAM_USERS: str = Field(
        default="",
        description="Comma-separated list of allowed Telegram user IDs or usernames"
    )

    # LLM Settings (OpenAI Compatible)
    OPENAI_API_KEY: str = Field(
        default="",
        description="API Key for OpenAI or compatible LLM provider"
    )
    OPENAI_BASE_URL: Optional[str] = Field(
        default=None,
        description="Optional base URL for OpenAI-compatible services"
    )
    LLM_MODEL: str = Field(
        default="gpt-4o",
        description="LLM model name to use across agents"
    )
    LLM_TEMPERATURE: float = Field(
        default=0.2,
        description="Temperature setting for code generation and planning"
    )

    # GitHub Deployment Settings
    GITHUB_TOKEN: str = Field(
        default="",
        description="GitHub personal access token for repository operations"
    )
    GITHUB_USERNAME: str = Field(
        default="",
        description="GitHub username or organization where repositories will be created"
    )

    # Workspace & File System Paths
    BASE_DIR: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent
    )
    WORKSPACE_DIR: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent / "workspace"
    )
    DB_PATH: Path = Field(
        default_factory=lambda: Path(__file__).resolve().parent / "agentic_memory.db"
    )
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///agentic_memory.db",
        description="Database connection string for SQLite with aiosqlite"
    )

    # System & Execution Tuning
    LOG_LEVEL: str = Field(
        default="INFO",
        description="Logging level for application execution"
    )
    MAX_SELF_CORRECTION_RETRIES: int = Field(
        default=3,
        description="Maximum iterations for self-correction loops upon error detection"
    )

    def setup_directories(self) -> None:
        """Create necessary system workspace and data directories if they do not exist."""
        self.WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
        if self.DB_PATH.parent:
            self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    def get_allowed_users_list(self) -> List[str]:
        """Parse comma-separated allowed Telegram user IDs/usernames into a list."""
        if not self.ALLOWED_TELEGRAM_USERS:
            return []
        return [user.strip() for user in self.ALLOWED_TELEGRAM_USERS.split(",") if user.strip()]


settings = Settings()
settings.setup_directories()
