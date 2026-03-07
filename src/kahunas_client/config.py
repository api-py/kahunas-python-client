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

    # WhatsApp Business API settings
    whatsapp_token: str = Field(default="", description="WhatsApp Cloud API access token")
    whatsapp_phone_number_id: str = Field(
        default="", description="WhatsApp Business phone number ID"
    )
    whatsapp_default_country_code: str = Field(
        default="44", description="Default country code for phone normalisation (44 = UK)"
    )

    # Calendar sync settings
    calendar_prefix: str = Field(
        default="Workout", description="Prefix for calendar event titles (e.g. 'Workout', 'PT')"
    )
    default_gym: str = Field(
        default="", description="Default gym/location for calendar appointments"
    )
    gym_list: str = Field(
        default="",
        description="Comma-separated list of available gyms (e.g. 'Gym A,Gym B,Home')",
    )
    calendar_default_duration: int = Field(
        default=60, description="Default appointment duration in minutes"
    )

    # Measurement unit settings (match Kahunas coach/configuration page)
    weight_unit: str = Field(default="kg", description="Weight unit: 'kg' or 'lbs'")
    height_unit: str = Field(default="cm", description="Height unit: 'cm' or 'inches'")
    glucose_unit: str = Field(
        default="mmol_l", description="Glucose level unit: 'mmol_l' or 'mg_dl'"
    )
    food_unit: str = Field(
        default="grams",
        description="Food unit: 'grams', 'ounces', 'qty', 'cups', 'oz', 'ml', 'tsp'",
    )
    water_unit: str = Field(default="ml", description="Water unit: 'ml', 'l', or 'oz'")

    # Timezone setting (from Kahunas coach/configuration page)
    timezone: str = Field(
        default="Europe/London",
        description="Timezone for appointments and scheduling (IANA format, e.g. 'Europe/London')",
    )

    # Check-in reminder settings
    checkin_reminder_days: int = Field(
        default=7, description="Days since last check-in before a client is considered overdue"
    )

    # Anomaly detection thresholds
    anomaly_weight_pct: float = Field(
        default=20.0, description="Weight % change threshold to flag as anomaly"
    )
    anomaly_body_pct: float = Field(
        default=15.0, description="Body measurement (waist/hips/biceps/thighs) % change threshold"
    )
    anomaly_lifestyle_abs: float = Field(
        default=3.0, description="Lifestyle rating (1-10 scale) absolute change threshold"
    )
    anomaly_window_days: int = Field(
        default=7, description="Lookback window in days for anomaly detection"
    )
    anomaly_sleep_minimum: float = Field(
        default=7.0, description="Sleep quality score below which to flag a warning"
    )
    anomaly_step_minimum: int = Field(
        default=5000, description="Daily step count below which to flag a warning"
    )

    # Persona / messaging template settings
    persona_template: str = Field(
        default="", description="Inline persona template text (overrides default)"
    )
    persona_template_path: str = Field(
        default="", description="Path to persona template file (highest priority)"
    )
    persona_weight_deviation_pct: float = Field(
        default=20.0, description="Weight deviation % to highlight in persona messages"
    )
    persona_sleep_minimum: float = Field(
        default=7.0, description="Sleep hours below which persona messages highlight concern"
    )
    persona_step_minimum: int = Field(
        default=5000, description="Step count below which persona messages highlight concern"
    )

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
