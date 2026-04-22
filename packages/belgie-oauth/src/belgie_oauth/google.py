from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from belgie_core.core.exceptions import OAuthError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from belgie_oauth.generic import OAuthClient, OAuthPlugin, OAuthProvider, OAuthTokenSet, OAuthUserInfo

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_oauth._transport import AuthlibOIDCClient


class GoogleUserInfo(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    sub: str | None = None
    id: str | None = None
    email: str | None = None
    email_verified: bool | None = None
    verified_email: bool | None = None
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None
    locale: str | None = None

    @property
    def resolved_subject(self) -> str | None:
        return self.sub or self.id

    @property
    def resolved_email_verified(self) -> bool:
        if self.email_verified is not None:
            return self.email_verified
        return self.verified_email is True


class GoogleOAuth(BaseSettings):
    DISCOVERY_URL: ClassVar[str] = "https://accounts.google.com/.well-known/openid-configuration"

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
    include_granted_scopes: bool = True
    hosted_domain: str | None = None
    disable_sign_up: bool = False
    disable_implicit_sign_up: bool = False
    override_user_info_on_sign_in: bool = False
    update_account_on_sign_in: bool = True
    allow_implicit_account_linking: bool = True
    allow_different_link_emails: bool = False
    trusted_for_account_linking: bool = False
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
        authorization_params = dict(self.authorization_params)
        if self.include_granted_scopes and "include_granted_scopes" not in authorization_params:
            authorization_params["include_granted_scopes"] = "true"
        if self.hosted_domain is not None and "hd" not in authorization_params:
            authorization_params["hd"] = self.hosted_domain

        return OAuthProvider(
            provider_id="google",
            client_id=self.client_id,
            client_secret=self.client_secret,
            discovery_url=self.DISCOVERY_URL,
            scopes=self.scopes,
            prompt=self.prompt,
            access_type=self.access_type,
            disable_sign_up=self.disable_sign_up,
            disable_implicit_sign_up=self.disable_implicit_sign_up,
            override_user_info_on_sign_in=self.override_user_info_on_sign_in,
            update_account_on_sign_in=self.update_account_on_sign_in,
            allow_implicit_account_linking=self.allow_implicit_account_linking,
            allow_different_link_emails=self.allow_different_link_emails,
            trusted_for_account_linking=self.trusted_for_account_linking,
            encrypt_tokens=self.encrypt_tokens,
            token_encryption_secret=self.token_encryption_secret,
            authorization_params=authorization_params,
            get_userinfo=_get_google_userinfo,
            map_profile=_map_google_profile,
        )

    def __call__(self, belgie_settings: BelgieSettings) -> GoogleOAuthPlugin:
        return GoogleOAuthPlugin(belgie_settings, self)


class GoogleOAuthClient(OAuthClient):
    pass


class GoogleOAuthPlugin(OAuthPlugin):
    DISCOVERY_URL = GoogleOAuth.DISCOVERY_URL
    TOKEN_URL = "https://oauth2.googleapis.com/token"
    USER_INFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

    def __init__(self, belgie_settings: BelgieSettings, settings: GoogleOAuth) -> None:
        self.settings = settings
        super().__init__(belgie_settings, settings.to_provider(), client_type=GoogleOAuthClient)


async def _get_google_userinfo(
    oauth_client: AuthlibOIDCClient,
    token_set: OAuthTokenSet,  # noqa: ARG001
    metadata: dict[str, object],
) -> dict[str, object] | None:
    userinfo_endpoint = metadata.get("userinfo_endpoint") or GoogleOAuthPlugin.USER_INFO_URL
    try:
        response = await oauth_client.get(str(userinfo_endpoint))
        response.raise_for_status()
        profile = response.json()
    except Exception:
        return None
    return profile if isinstance(profile, dict) else None


def _map_google_profile(raw_profile: dict[str, object], token_set: OAuthTokenSet) -> OAuthUserInfo:  # noqa: ARG001
    profile = GoogleUserInfo(**raw_profile)
    if profile.resolved_subject is None:
        msg = "provider user info missing subject identifier"
        raise OAuthError(msg)
    return OAuthUserInfo(
        provider_account_id=profile.resolved_subject,
        email=profile.email,
        email_verified=profile.resolved_email_verified,
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
