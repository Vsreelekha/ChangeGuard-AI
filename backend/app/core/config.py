from functools import lru_cache
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings loaded from environment or .env file."""

    # Project metadata
    PROJECT_NAME: str = "ChangeGuard AI API"
    VERSION: str = "1.0.0"
    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    # CORS origins
    CORS_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    # Database configuration
    # Default to SQLite for seamless local dev; set POSTGRES_URL in production
    DATABASE_URL: str = "sqlite:///./changeguard.db"

    # Safe Pytest / Docker Runner Configuration
    DOCKER_IMAGE: str = "changeguard-runner:latest"
    DOCKER_TIMEOUT_SECONDS: int = 60
    DOCKER_MEMORY_LIMIT: str = "512m"
    DOCKER_CPU_LIMIT: float = 1.0
    DOCKER_PIDS_LIMIT: int = 100
    # Must be explicitly configured as a JSON list of absolute directory paths.
    APPROVED_PROJECT_ROOTS: List[str] = []

    # Private server-side workspaces for uploaded projects. This must be an
    # existing directory inside one of APPROVED_PROJECT_ROOTS and outside any
    # publicly served directory.
    PROJECT_WORKSPACE_ROOT: str = ""
    PROJECT_UPLOAD_MAX_BYTES: int = Field(default=50 * 1024 * 1024, gt=0)
    PROJECT_EXTRACTED_MAX_BYTES: int = Field(default=250 * 1024 * 1024, gt=0)
    PROJECT_FILE_MAX_BYTES: int = Field(default=25 * 1024 * 1024, gt=0)
    PROJECT_ARCHIVE_MAX_FILES: int = Field(default=10_000, gt=0)
    PROJECT_ARCHIVE_MAX_ENTRIES: int = Field(default=10_000, gt=0)
    PROJECT_ARCHIVE_MAX_DEPTH: int = Field(default=32, gt=0)
    PROJECT_WORKSPACE_TTL_HOURS: int = Field(default=24, gt=0)
    PROJECT_STAGING_TTL_HOURS: int = Field(default=24, gt=0)
    PROJECT_WORKSPACE_MAX_BYTES: int = Field(default=2 * 1024 * 1024 * 1024, gt=0)
    PROJECT_UPLOAD_MAX_CONCURRENT: int = Field(default=2, gt=0)

    # Integration flags / settings
    ANALYZER_MODULE_ENABLED: bool = True
    TEST_SELECTOR_MODULE_ENABLED: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Cached settings instance to avoid re-reading disk."""
    return Settings()
