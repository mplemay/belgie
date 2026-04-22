from __future__ import annotations

import base64
from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlparse, urlunparse

from belgie_core.core.exceptions import OAuthError
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from belgie_oauth._helpers import serialize_scopes
from belgie_oauth.generic import OAuthClient, OAuthPlugin, OAuthProvider, OAuthTokenSet, OAuthUserInfo

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings

    from belgie_oauth._transport import AuthlibOIDCClient


class MicrosoftUserInfo(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    sub: str
    email: str | None = None
    preferred_username: str | None = None
    upn: str | None = None
    name: str | None = None
    given_name: str | None = None
    family_name: str | None = None
    picture: str | None = None
    email_verified: bool | None = None
    verified_primary_email: list[str] | None = None
    verified_secondary_email: list[str] | None = None

    @property
    def resolved_email(self) -> str | None:
        if self.email is not None:
            return self.email
        if self.preferred_username is not None:
            return self.preferred_username
        if self.upn is not None:
            return self.upn
        if self.verified_primary_email:
            return self.verified_primary_email[0]
        if self.verified_secondary_email:
            return self.verified_secondary_email[0]
        return None

    @property
    def resolved_email_verified(self) -> bool:
        if self.email_verified is not None:
            return self.email_verified
        if self.resolved_email is None:
            return False
        return self._email_in(self.verified_primary_email) or self._email_in(self.verified_secondary_email)

    def _email_in(self, values: list[str] | None) -> bool:
        return values is not None and any(value.casefold() == self.resolved_email.casefold() for value in values)


class MicrosoftOAuth(BaseSettings):
    DEFAULT_TENANT: ClassVar[str] = "common"
    DEFAULT_AUTHORITY: ClassVar[str] = "https://login.microsoftonline.com"
    USER_INFO_URL: ClassVar[str] = "https://graph.microsoft.com/oidc/userinfo"
    PROFILE_PHOTO_SIZES: ClassVar[frozenset[int]] = frozenset({48, 64, 96, 120, 240, 360, 432, 504, 648})

    model_config = SettingsConfigDict(
        env_prefix="BELGIE_MICROSOFT_",
        env_file=".env",
        extra="ignore",
    )

    client_id: str
    client_secret: SecretStr | None = None
    tenant: str = Field(default=DEFAULT_TENANT)
    authority: str = Field(default=DEFAULT_AUTHORITY)
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email", "offline_access", "User.Read"])
    disable_profile_photo: bool = False
    profile_photo_size: int = 48
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

    @field_validator("client_id", "tenant", "authority")
    @classmethod
    def validate_non_empty(cls, value: str, info: ValidationInfo) -> str:
        if not value or not value.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        normalized = value.strip()
        if info.field_name == "authority":
            return normalized.rstrip("/")
        return normalized

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

    @field_validator("profile_photo_size")
    @classmethod
    def validate_profile_photo_size(cls, value: int) -> int:
        if value not in cls.PROFILE_PHOTO_SIZES:
            msg = f"profile_photo_size must be one of {sorted(cls.PROFILE_PHOTO_SIZES)}"
            raise ValueError(msg)
        return value

    def to_provider(self) -> OAuthProvider:
        issuer = None
        if self.tenant not in {"common", "organizations", "consumers"}:
            issuer = _authority_url(self.authority, path=f"/{self.tenant}/v2.0")

        return OAuthProvider(
            provider_id="microsoft",
            client_id=self.client_id,
            client_secret=self.client_secret,
            authorization_endpoint=_authority_url(
                self.authority,
                path=f"/{self.tenant}/oauth2/v2.0/authorize",
            ),
            token_endpoint=_authority_url(
                self.authority,
                path=f"/{self.tenant}/oauth2/v2.0/token",
            ),
            userinfo_endpoint=self.USER_INFO_URL,
            jwks_uri=_authority_url(
                self.authority,
                path=f"/{self.tenant}/discovery/v2.0/keys",
            ),
            issuer=issuer,
            scopes=self.scopes,
            response_mode="query",
            disable_sign_up=self.disable_sign_up,
            disable_implicit_sign_up=self.disable_implicit_sign_up,
            override_user_info_on_sign_in=self.override_user_info_on_sign_in,
            update_account_on_sign_in=self.update_account_on_sign_in,
            allow_implicit_account_linking=self.allow_implicit_account_linking,
            allow_different_link_emails=self.allow_different_link_emails,
            trusted_for_account_linking=self.trusted_for_account_linking,
            encrypt_tokens=self.encrypt_tokens,
            token_encryption_secret=self.token_encryption_secret,
            authorization_params=self.authorization_params,
            token_endpoint_auth_method="none" if self.client_secret is None else "client_secret_post",
            get_userinfo=_build_microsoft_userinfo_fetcher(
                disable_profile_photo=self.disable_profile_photo,
                profile_photo_size=self.profile_photo_size,
            ),
            refresh_tokens=_build_microsoft_refresh_handler(self.scopes),
            map_profile=_map_microsoft_profile,
        )

    def __call__(self, belgie_settings: BelgieSettings) -> MicrosoftOAuthPlugin:
        return MicrosoftOAuthPlugin(belgie_settings, self)


class MicrosoftOAuthClient(OAuthClient):
    pass


class MicrosoftOAuthPlugin(OAuthPlugin):
    DEFAULT_AUTHORITY = MicrosoftOAuth.DEFAULT_AUTHORITY
    USER_INFO_URL = MicrosoftOAuth.USER_INFO_URL

    def __init__(self, belgie_settings: BelgieSettings, settings: MicrosoftOAuth) -> None:
        self.settings = settings
        super().__init__(belgie_settings, settings.to_provider(), client_type=MicrosoftOAuthClient)

    @staticmethod
    def profile_photo_url(size: int) -> str:
        return f"https://graph.microsoft.com/v1.0/me/photos/{size}x{size}/$value"


def _authority_url(authority: str, *, path: str) -> str:
    parsed = urlparse(authority)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            f"{parsed.path.rstrip('/')}{path}",
            "",
            "",
            "",
        ),
    )


def _build_microsoft_userinfo_fetcher(*, disable_profile_photo: bool, profile_photo_size: int):
    async def get_userinfo(
        oauth_client: AuthlibOIDCClient,
        token_set: OAuthTokenSet,  # noqa: ARG001
        metadata: dict[str, object],
    ) -> dict[str, object] | None:
        userinfo_endpoint = metadata.get("userinfo_endpoint") or MicrosoftOAuthPlugin.USER_INFO_URL
        response = await oauth_client.get(str(userinfo_endpoint))
        response.raise_for_status()
        profile = response.json()
        if not isinstance(profile, dict):
            msg = "provider user info missing profile data"
            raise OAuthError(msg)

        if not disable_profile_photo:
            try:
                photo_response = await oauth_client.get(
                    MicrosoftOAuthPlugin.profile_photo_url(profile_photo_size),
                )
            except Exception:
                photo_response = None
            if photo_response is not None and photo_response.is_success:
                content_type = photo_response.headers.get("content-type", "image/jpeg")
                encoded = base64.b64encode(photo_response.content).decode("ascii")
                profile["picture"] = f"data:{content_type};base64,{encoded}"

        return profile

    return get_userinfo


def _build_microsoft_refresh_handler(scopes: list[str]):
    async def refresh_tokens(
        oauth_client: AuthlibOIDCClient,
        token_set: OAuthTokenSet,
        token_params: dict[str, str],
    ) -> dict[str, object]:
        if token_set.refresh_token is None:
            msg = "oauth account does not have a refresh token"
            raise OAuthError(msg)

        metadata = await oauth_client.load_server_metadata()
        token_endpoint = metadata.get("token_endpoint")
        if not token_endpoint:
            msg = "missing required provider metadata: token_endpoint"
            raise OAuthError(msg)

        refresh_params = dict(token_params)
        if "scope" not in refresh_params:
            refresh_params["scope"] = token_set.scope or serialize_scopes(scopes)

        raw_token = await oauth_client.refresh_token(
            str(token_endpoint),
            refresh_token=token_set.refresh_token,
            **refresh_params,
        )
        return dict(raw_token)

    return refresh_tokens


def _map_microsoft_profile(raw_profile: dict[str, object], token_set: OAuthTokenSet) -> OAuthUserInfo:  # noqa: ARG001
    profile = MicrosoftUserInfo(**raw_profile)
    return OAuthUserInfo(
        provider_account_id=profile.sub,
        email=profile.resolved_email,
        email_verified=profile.resolved_email_verified,
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
