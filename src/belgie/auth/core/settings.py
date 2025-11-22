from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class SessionSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BELGIE_SESSION_")

    max_age: int = Field(default=604800)
    update_age: int = Field(default=86400)


class CookieSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BELGIE_COOKIE_")

    name: str = Field(default="belgie_session")
    secure: bool = Field(default=True)
    http_only: bool = Field(default=True)
    same_site: Literal["lax", "strict", "none"] = Field(default="lax")
    domain: str | None = Field(default=None)


class GoogleOAuthSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BELGIE_GOOGLE_")

    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: list[str] = Field(default=["openid", "email", "profile"])

    @field_validator("client_id", "client_secret", "redirect_uri")
    @classmethod
    def validate_non_empty(cls, v: str, info) -> str:  # noqa: ANN001
        """Ensure required OAuth fields are non-empty."""
        if not v or not v.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        return v.strip()


class URLSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BELGIE_URLS_")

    signin_redirect: str = Field(default="/dashboard")
    signout_redirect: str = Field(default="/")


class AuthSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    secret: str
    base_url: str

    session: SessionSettings = Field(default_factory=SessionSettings)
    cookie: CookieSettings = Field(default_factory=CookieSettings)
    google: GoogleOAuthSettings = Field(default_factory=GoogleOAuthSettings)
    urls: URLSettings = Field(default_factory=URLSettings)
