from abc import abstractmethod
from typing import TYPE_CHECKING, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

if TYPE_CHECKING:
    from auth.providers.protocols import OAuthProviderProtocol


class ProviderSettings(BaseSettings):
    """Base settings class for OAuth providers.

    All provider-specific settings should inherit from this class
    to ensure consistent configuration structure.

    Subclasses must implement __call__ to construct their provider instance.
    """

    client_id: str
    client_secret: SecretStr
    redirect_uri: str

    @field_validator("client_id", "redirect_uri")
    @classmethod
    def validate_non_empty(cls, v: str, info) -> str:  # noqa: ANN001
        """Ensure required OAuth fields are non-empty."""
        if not v or not v.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        return v.strip()

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, v: SecretStr) -> SecretStr:
        """Ensure client_secret is non-empty and trim whitespace."""
        secret_value = v.get_secret_value()
        if not secret_value or not secret_value.strip():
            msg = "client_secret must be a non-empty string"
            raise ValueError(msg)
        # Return a new SecretStr with trimmed value
        return SecretStr(secret_value.strip())

    @abstractmethod
    def __call__(self) -> "OAuthProviderProtocol":
        """Create and return the OAuth provider instance.

        Returns:
            OAuth provider configured with these settings
        """
        ...


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
    urls: URLSettings = Field(default_factory=URLSettings)

    @field_validator("secret", "base_url")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:  # noqa: ANN001
        """Ensure required Auth settings are non-empty."""
        if not value or not value.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        return value.strip()
