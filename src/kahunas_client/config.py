"""Configuration for the Kahunas client."""

from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class KahunasConfig(BaseSettings):
    """Configuration loaded from env vars (KAHUNAS_*), YAML, or direct args."""

    model_config = SettingsConfigDict(env_prefix="KAHUNAS_", env_file=".env", extra="ignore")

    api_base_url: str = Field(default="https://api.kahunas.io/api", description="API base URL")
    web_base_url: str = Field(default="https://kahunas.io", description="Web app base URL")
    email: str = Field(default="", description="Account email for authentication")
    password: str = Field(default="", description="Account password for authentication")
    auth_token: str = Field(default="", description="Pre-existing auth token (skips login)")
    timeout: float = Field(default=30.0, description="HTTP request timeout in seconds")
    max_retries: int = Field(default=3, description="Max retry attempts for failed requests")
    retry_base_delay: float = Field(default=1.0, description="Base delay between retries (seconds)")

    @classmethod
    def from_yaml(cls, path: str | Path) -> KahunasConfig:
        """Load config from a YAML file, merged with env vars."""
        config_path = Path(path)
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            return cls(**data)
        return cls()

    @classmethod
    def from_env(cls) -> KahunasConfig:
        """Load config from environment variables and optional .env file."""
        yaml_path = os.getenv("KAHUNAS_CONFIG_FILE", "")
        if yaml_path:
            return cls.from_yaml(yaml_path)
        return cls()
