from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_SESSION_",
        env_file=".env",
        extra="ignore",
    )

    max_age: int = Field(default=604800)
    update_age: int = Field(default=86400)


class CookieSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_COOKIE_",
        env_file=".env",
        extra="ignore",
    )

    name: str = Field(default="belgie_session")
    secure: bool = Field(default=True)
    http_only: bool = Field(default=True)
    same_site: Literal["lax", "strict", "none"] = Field(default="lax")
    domain: str | None = Field(default=None)


class URLSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_URLS_",
        env_file=".env",
        extra="ignore",
    )

    signin_redirect: str = Field(default="/dashboard")
    signout_redirect: str = Field(default="/")


class BelgieSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    secret: str
    base_url: str

    session: SessionSettings = Field(default_factory=SessionSettings)
    cookie: CookieSettings = Field(default_factory=CookieSettings)
    urls: URLSettings = Field(default_factory=URLSettings)

    @field_validator("secret", "base_url")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:  # noqa: ANN001
        """Ensure required Belgie settings are non-empty."""
        if not value or not value.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        return value.strip()
