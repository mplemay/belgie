from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from belgie_oauth.generic import OAuthClient, OAuthPlugin, OAuthProvider, OAuthTokenSet, OAuthUserInfo

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings


class GoogleUserInfo(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    sub: str
    email: str
    email_verified: bool
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None
    locale: str | None = None


class GoogleOAuth(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_GOOGLE_",
        env_file=".env",
        extra="ignore",
    )

    client_id: str
    client_secret: SecretStr
    scopes: list[str] = Field(default_factory=lambda: ["openid", "email", "profile"])
    access_type: str = Field(default="offline")
    prompt: str = Field(default="consent")
    disable_sign_up: bool = False
    disable_implicit_sign_up: bool = False
    encrypt_tokens: bool = False
    token_encryption_secret: SecretStr | None = None
    authorization_params: dict[str, str] = Field(default_factory=dict)

    @field_validator("client_id")
    @classmethod
    def validate_client_id(cls, value: str, info) -> str:  # noqa: ANN001
        if not value or not value.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        return value.strip()

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, value: SecretStr) -> SecretStr:
        secret = value.get_secret_value().strip()
        if not secret:
            msg = "client_secret must be a non-empty string"
            raise ValueError(msg)
        return SecretStr(secret)

    def to_provider(self) -> OAuthProvider:
        return OAuthProvider(
            provider_id="google",
            client_id=self.client_id,
            client_secret=self.client_secret,
            discovery_url="https://accounts.google.com/.well-known/openid-configuration",
            scopes=self.scopes,
            prompt=self.prompt,
            access_type=self.access_type,
            disable_sign_up=self.disable_sign_up,
            disable_implicit_sign_up=self.disable_implicit_sign_up,
            encrypt_tokens=self.encrypt_tokens,
            token_encryption_secret=self.token_encryption_secret,
            authorization_params=self.authorization_params,
            map_profile=_map_google_profile,
        )

    def __call__(self, belgie_settings: BelgieSettings) -> GoogleOAuthPlugin:
        return GoogleOAuthPlugin(belgie_settings, self)


class GoogleOAuthClient(OAuthClient):
    pass


class GoogleOAuthPlugin(OAuthPlugin):
    def __init__(self, belgie_settings: BelgieSettings, settings: GoogleOAuth) -> None:
        self.settings = settings
        super().__init__(belgie_settings, settings.to_provider(), client_type=GoogleOAuthClient)


def _map_google_profile(raw_profile: dict[str, object], token_set: OAuthTokenSet) -> OAuthUserInfo:  # noqa: ARG001
    profile = GoogleUserInfo(**raw_profile)
    return OAuthUserInfo(
        provider_account_id=profile.sub,
        email=profile.email,
        email_verified=profile.email_verified,
        name=profile.name,
        image=profile.picture,
        raw=dict(raw_profile),
    )


__all__ = [
    "GoogleOAuth",
    "GoogleOAuthClient",
    "GoogleOAuthPlugin",
    "GoogleUserInfo",
]
