from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from belgie_oauth.generic import OAuthClient, OAuthPlugin, OAuthProvider, OAuthTokenSet, OAuthUserInfo

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings


class MicrosoftUserInfo(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    sub: str
    email: str | None = None
    preferred_username: str | None = None
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None
    email_verified: bool | None = None

    @property
    def resolved_email(self) -> str | None:
        return self.email or self.preferred_username


class MicrosoftOAuth(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_MICROSOFT_",
        env_file=".env",
        extra="ignore",
    )

    client_id: str
    client_secret: SecretStr | None = None
    tenant: str = Field(default="common")
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email", "offline_access", "User.Read"])
    disable_sign_up: bool = False
    disable_implicit_sign_up: bool = False
    encrypt_tokens: bool = False
    token_encryption_secret: SecretStr | None = None
    authorization_params: dict[str, str] = Field(default_factory=dict)

    @field_validator("client_id", "tenant")
    @classmethod
    def validate_non_empty(cls, value: str, info: ValidationInfo) -> str:
        if not value or not value.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        return value.strip()

    @field_validator("client_secret")
    @classmethod
    def validate_client_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        secret = value.get_secret_value().strip()
        if not secret:
            msg = "client_secret must be a non-empty string"
            raise ValueError(msg)
        return SecretStr(secret)

    def to_provider(self) -> OAuthProvider:
        issuer = None
        if self.tenant not in {"common", "organizations", "consumers"}:
            issuer = f"https://login.microsoftonline.com/{self.tenant}/v2.0"

        return OAuthProvider(
            provider_id="microsoft",
            client_id=self.client_id,
            client_secret=self.client_secret,
            authorization_endpoint=f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/authorize",
            token_endpoint=f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token",
            userinfo_endpoint="https://graph.microsoft.com/oidc/userinfo",
            jwks_uri=f"https://login.microsoftonline.com/{self.tenant}/discovery/v2.0/keys",
            issuer=issuer,
            scopes=self.scopes,
            response_mode="query",
            disable_sign_up=self.disable_sign_up,
            disable_implicit_sign_up=self.disable_implicit_sign_up,
            encrypt_tokens=self.encrypt_tokens,
            token_encryption_secret=self.token_encryption_secret,
            authorization_params=self.authorization_params,
            token_endpoint_auth_method="none" if self.client_secret is None else "client_secret_post",
            map_profile=_map_microsoft_profile,
        )

    def __call__(self, belgie_settings: BelgieSettings) -> MicrosoftOAuthPlugin:
        return MicrosoftOAuthPlugin(belgie_settings, self)


class MicrosoftOAuthClient(OAuthClient):
    pass


class MicrosoftOAuthPlugin(OAuthPlugin):
    def __init__(self, belgie_settings: BelgieSettings, settings: MicrosoftOAuth) -> None:
        self.settings = settings
        super().__init__(belgie_settings, settings.to_provider(), client_type=MicrosoftOAuthClient)


def _map_microsoft_profile(raw_profile: dict[str, object], token_set: OAuthTokenSet) -> OAuthUserInfo:  # noqa: ARG001
    profile = MicrosoftUserInfo(**raw_profile)
    return OAuthUserInfo(
        provider_account_id=profile.sub,
        email=profile.resolved_email,
        email_verified=profile.email_verified if profile.email_verified is not None else False,
        name=profile.name,
        image=profile.picture,
        raw=dict(raw_profile),
    )


__all__ = [
    "MicrosoftOAuth",
    "MicrosoftOAuthClient",
    "MicrosoftOAuthPlugin",
    "MicrosoftUserInfo",
]
