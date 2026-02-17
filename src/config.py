"""Runtime configuration for the research pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os


@dataclass(frozen=True)
class Settings:
    """Environment-backed application settings."""

    # Supabase / Postgres
    supabase_url: str
    supabase_service_role_key: str
    postgres_dsn: str

    # Anthropic
    anthropic_api_key: str
    anthropic_model_id: str
    anthropic_small_model_id: str

    # OpenAI
    openai_api_key: str
    openai_embedding_model: str

    # Transcript provider
    transcript_api_key: str

    # GitHub delivery metadata
    github_token: str
    github_owner: str
    github_repo: str
    github_default_branch: str



def _get_env(name: str, *, default: str | None = None, required: bool = False) -> str:
    value = os.getenv(name, default)
    if required and (value is None or value == ""):
        raise ValueError(f"Missing required environment variable: {name}")
    if value is None:
        return ""
    return value


@lru_cache(maxsize=1)
def load_settings() -> Settings:
    """Load and cache Settings from environment variables."""

    return Settings(
        supabase_url=_get_env("SUPABASE_URL", required=True),
        supabase_service_role_key=_get_env("SUPABASE_SERVICE_ROLE_KEY", required=True),
        postgres_dsn=_get_env("POSTGRES_DSN", required=True),
        anthropic_api_key=_get_env("ANTHROPIC_API_KEY", required=True),
        anthropic_model_id=_get_env("ANTHROPIC_MODEL_ID", default="claude-3-5-sonnet-latest"),
        anthropic_small_model_id=_get_env("ANTHROPIC_SMALL_MODEL_ID", default="claude-3-5-haiku-latest"),
        openai_api_key=_get_env("OPENAI_API_KEY", required=True),
        openai_embedding_model=_get_env("OPENAI_EMBEDDING_MODEL", default="text-embedding-3-large"),
        transcript_api_key=_get_env("TRANSCRIPT_API_KEY", required=True),
        github_token=_get_env("GITHUB_TOKEN", required=True),
        github_owner=_get_env("GITHUB_OWNER", required=True),
        github_repo=_get_env("GITHUB_REPO", required=True),
        github_default_branch=_get_env("GITHUB_DEFAULT_BRANCH", default="main"),
    )
