"""Trace module settings."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class TraceSettings(BaseSettings):
    """Settings for the trace module.

    Environment variables are prefixed with BELGIE_TRACE_.
    Example: BELGIE_TRACE_ENABLED=false
    """

    model_config = SettingsConfigDict(
        env_prefix="BELGIE_TRACE_",
        env_file=".env",
        env_file_encoding="utf-8",
    )

    enabled: bool = Field(default=True)
