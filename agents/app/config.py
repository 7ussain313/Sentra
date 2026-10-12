from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven settings. Secrets arrive via .env / env_file, never code."""

    model_config = SettingsConfigDict(extra="ignore", case_sensitive=False)

    audit_dir: Path = Path("/app/audit")
    compose_project: str = "sentra"

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
