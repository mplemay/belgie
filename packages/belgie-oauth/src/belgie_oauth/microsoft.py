from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar
from urllib.parse import urlparse, urlunparse

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator
from pydantic_settings import SettingsConfigDict

from belgie_oauth._strategy import MicrosoftOAuthStrategy, OAuthPresetSettings, microsoft_profile_photo_url
from belgie_oauth.generic import OAuthClient, OAuthPlugin, OAuthProvider, OAuthTokenSet, OAuthUserInfo

if TYPE_CHECKING:
    from belgie_core.core.settings import BelgieSettings


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


class MicrosoftOAuth(OAuthPresetSettings):
    DEFAULT_TENANT: ClassVar[str] = "common"
    DEFAULT_AUTHORITY: ClassVar[str] = "https://login.microsoftonline.com"
    USER_INFO_URL: ClassVar[str] = "https://graph.microsoft.com/oidc/userinfo"
    PROFILE_PHOTO_SIZES: ClassVar[frozenset[int]] = frozenset({48, 64, 96, 120, 240, 360, 432, 504, 648})

    model_config = SettingsConfigDict(
        env_prefix="BELGIE_MICROSOFT_",
        env_file=".env",
        extra="ignore",
    )

    tenant: str = Field(default=DEFAULT_TENANT)
    authority: str = Field(default=DEFAULT_AUTHORITY)
    scopes: list[str] = Field(default_factory=lambda: ["openid", "profile", "email", "offline_access", "User.Read"])
    disable_profile_photo: bool = False
    profile_photo_size: int = 48

    @field_validator("tenant", "authority")
    @classmethod
    def validate_non_empty(cls, value: str, info: ValidationInfo) -> str:
        if not value or not value.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        normalized = value.strip()
        if info.field_name == "authority":
            return normalized.rstrip("/")
        return normalized

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
            response_mode=self.response_mode or "query",
            state_strategy=self.state_strategy,
            use_pkce=self.use_pkce,
            code_challenge_method=self.code_challenge_method,
            use_nonce=self.use_nonce,
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
            token_params=self.token_params,
            discovery_headers=self.discovery_headers,
            token_endpoint_auth_method="none" if self.client_secret is None else "client_secret_post",
            strategy=MicrosoftOAuthStrategy(
                scopes=self.scopes,
                disable_profile_photo=self.disable_profile_photo,
                profile_photo_size=self.profile_photo_size,
            ),
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
        return microsoft_profile_photo_url(size)


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
