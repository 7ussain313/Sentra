from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings. Secrets arrive via .env / env_file, never code."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    audit_dir: Path = Path("/app/audit")
    incidents_dir: Path = Path("/app/incidents")
    compose_project: str = "sentra"

    # "anthropic" (default) or "openai_compat" (Gemini/Groq/Ollama via LLM_BASE_URL + LLM_API_KEY)
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai"
    llm_model: str = "claude-sonnet-5-5"
    max_steps: int = 8
    approval_timeout_seconds: int = 600
    dedupe_window_seconds: int = 600

    prometheus_url: str = "http://prometheus:9090"

    odoo_url: str = "http://odoo:8069"
    odoo_db_name: str = "sentra"
    odoo_agent_login: str = "sentra_agent"
    odoo_agent_api_key: str = ""

    db_host: str = "db"
    db_port: int = 5432
    agent_db_ro_password: str = ""
    agent_db_signal_password: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
