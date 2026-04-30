from __future__ import annotations

# ruff: noqa: PLR0913, TC001
import base64
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from belgie_core.core.exceptions import OAuthError
from belgie_core.utils.callbacks import maybe_awaitable
from httpx import HTTPError
from pydantic import Field, SecretStr, ValidationInfo, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from belgie_oauth._errors import OAuthCallbackError
from belgie_oauth._helpers import coerce_optional_str, normalize_client_id, serialize_scopes
from belgie_oauth._models import OAuthTokenSet, OAuthUserInfo
from belgie_oauth._types import OAuthResponseMode, OAuthStateStrategy

if TYPE_CHECKING:
    from belgie_oauth._config import OAuthProvider
    from belgie_oauth._transport import AuthlibOIDCClient
    from belgie_oauth._types import (
        ProviderMetadata,
        RawProfile,
        TokenResponsePayload,
    )


class OAuthPresetSettings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    client_id: str | list[str]
    client_secret: SecretStr | None = None
    scopes: list[str] = Field(default_factory=list)
    response_mode: OAuthResponseMode | None = None
    state_strategy: OAuthStateStrategy = "adapter"
    use_pkce: bool = True
    code_challenge_method: str = "S256"
    use_nonce: bool = True
    authorization_params: dict[str, str] = Field(default_factory=dict)
    token_params: dict[str, str] = Field(default_factory=dict)
    discovery_headers: dict[str, str] = Field(default_factory=dict)
    disable_sign_up: bool = False
    disable_implicit_sign_up: bool = False
    disable_id_token_sign_in: bool = False
    override_user_info_on_sign_in: bool = False
    update_account_on_sign_in: bool = True
    allow_implicit_account_linking: bool = True
    allow_different_link_emails: bool = False
    trusted_for_account_linking: bool = False
    store_account_cookie: bool = False
    default_error_redirect_url: str | None = None
    encrypt_tokens: bool = False
    token_encryption_secret: SecretStr | None = None

    @field_validator("client_id")
    @classmethod
    def validate_client_id(cls, value: str | list[str], info: ValidationInfo) -> str | list[str]:
        return normalize_client_id(value, field_name=info.field_name or "client_id")

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


def microsoft_profile_photo_url(size: int) -> str:
    return f"https://graph.microsoft.com/v1.0/me/photos/{size}x{size}/$value"


class OAuthProviderStrategy(ABC):
    def build_authorization_params(
        self,
        *,
        config: OAuthProvider,
        prompt: str | None,
        access_type: str | None,
        response_mode: OAuthResponseMode | None,
        authorization_params: dict[str, str] | None,
        code_verifier: str | None,
        nonce: str | None,
    ) -> dict[str, str]:
        params = dict(config.authorization_params)
        if authorization_params:
            params.update(authorization_params)
        if prompt is not None:
            params["prompt"] = prompt
        elif config.prompt is not None:
            params["prompt"] = config.prompt
        if access_type is not None:
            params["access_type"] = access_type
        elif config.access_type is not None:
            params["access_type"] = config.access_type
        if response_mode is not None:
            params["response_mode"] = response_mode
        elif config.response_mode is not None:
            params["response_mode"] = config.response_mode
        if nonce is not None:
            params["nonce"] = nonce
        if code_verifier is not None and config.code_challenge_method == "plain":
            params["code_challenge"] = code_verifier
            params["code_challenge_method"] = "plain"
        return params

    @abstractmethod
    async def exchange_code_for_tokens(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        config: OAuthProvider,
        code: str,
        redirect_uri: str,
        code_verifier: str | None,
        token_endpoint: str,
    ) -> TokenResponsePayload: ...

    @abstractmethod
    async def refresh_token_response(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        config: OAuthProvider,
        token_set: OAuthTokenSet,
        token_endpoint: str,
    ) -> TokenResponsePayload: ...

    @abstractmethod
    async def resolve_profile(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        config: OAuthProvider,
        token_set: OAuthTokenSet,
        metadata: ProviderMetadata,
        id_token_claims: RawProfile,
    ) -> OAuthUserInfo: ...


class DefaultOAuthProviderStrategy(OAuthProviderStrategy):
    async def exchange_code_for_tokens(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        config: OAuthProvider,
        code: str,
        redirect_uri: str,
        code_verifier: str | None,
        token_endpoint: str,
    ) -> TokenResponsePayload:
        if config.get_token is not None:
            token = await config.get_token(
                oauth_client,
                code,
                dict(config.token_params),
                code_verifier,
            )
            return dict(token)

        token = await oauth_client.fetch_token(
            token_endpoint,
            code=code,
            grant_type="authorization_code",
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            **config.token_params,
        )
        return dict(token)

    async def refresh_token_response(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        config: OAuthProvider,
        token_set: OAuthTokenSet,
        token_endpoint: str,
    ) -> TokenResponsePayload:
        token_params = dict(config.token_params)
        if config.refresh_tokens is not None:
            raw_token = await config.refresh_tokens(oauth_client, token_set, token_params)
            return dict(raw_token)

        if token_set.refresh_token is None:
            msg = "oauth account does not have a refresh token"
            raise OAuthError(msg)

        raw_token = await oauth_client.refresh_token(
            token_endpoint,
            refresh_token=token_set.refresh_token,
            **token_params,
        )
        return dict(raw_token)

    async def resolve_profile(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        config: OAuthProvider,
        token_set: OAuthTokenSet,
        metadata: ProviderMetadata,
        id_token_claims: RawProfile,
    ) -> OAuthUserInfo:
        raw_profile = dict(id_token_claims)
        if fetched_profile := await self.fetch_userinfo(
            oauth_client=oauth_client,
            config=config,
            token_set=token_set,
            metadata=metadata,
        ):
            if isinstance(fetched_profile, OAuthUserInfo):
                if not raw_profile:
                    return fetched_profile
                merged_raw = dict(raw_profile)
                merged_raw.update(fetched_profile.raw)
                return OAuthUserInfo(
                    provider_account_id=fetched_profile.provider_account_id,
                    email=fetched_profile.email,
                    email_verified=fetched_profile.email_verified,
                    name=fetched_profile.name,
                    image=fetched_profile.image,
                    raw=merged_raw,
                )
            raw_profile.update(fetched_profile)

        if not raw_profile:
            error_code = "user_info_missing"
            description = "provider did not return a usable profile"
            raise OAuthCallbackError(error_code, description)
        return await self.map_profile(config, raw_profile, token_set)

    async def fetch_userinfo(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        config: OAuthProvider,
        token_set: OAuthTokenSet,
        metadata: ProviderMetadata,
    ) -> RawProfile | OAuthUserInfo | None:
        if config.get_userinfo is not None:
            return await config.get_userinfo(oauth_client, token_set, metadata)
        if token_set.access_token is None:
            return None
        if metadata.get("userinfo_endpoint") is None:
            return None
        try:
            profile = await oauth_client.userinfo()
        except Exception as exc:
            error_code = "user_info_missing"
            description = "failed to fetch provider user info"
            raise OAuthCallbackError(error_code, description) from exc
        return dict(profile)

    async def map_profile(
        self,
        config: OAuthProvider,
        raw_profile: RawProfile,
        token_set: OAuthTokenSet,
    ) -> OAuthUserInfo:
        if config.map_profile is not None:
            return await maybe_awaitable(config.map_profile)(raw_profile, token_set)

        provider_account_id = coerce_optional_str(raw_profile.get("sub")) or coerce_optional_str(raw_profile.get("id"))
        if provider_account_id is None:
            msg = "provider user info missing subject identifier"
            raise OAuthError(msg)

        email_verified = False
        if isinstance(email_verified_value := raw_profile.get("email_verified"), bool):
            email_verified = email_verified_value
        elif isinstance(verified_email_value := raw_profile.get("verified_email"), bool):
            email_verified = verified_email_value

        return OAuthUserInfo(
            provider_account_id=provider_account_id,
            email=coerce_optional_str(raw_profile.get("email")),
            email_verified=email_verified,
            name=coerce_optional_str(raw_profile.get("name")),
            image=coerce_optional_str(raw_profile.get("picture")) or coerce_optional_str(raw_profile.get("avatar_url")),
            raw=dict(raw_profile),
        )


class GoogleOAuthStrategy(DefaultOAuthProviderStrategy):
    async def resolve_profile(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        config: OAuthProvider,
        token_set: OAuthTokenSet,
        metadata: ProviderMetadata,
        id_token_claims: RawProfile,
    ) -> OAuthUserInfo:
        if config.get_userinfo is not None:
            return await super().resolve_profile(
                oauth_client=oauth_client,
                config=config,
                token_set=token_set,
                metadata=metadata,
                id_token_claims=id_token_claims,
            )

        if id_token_claims:
            try:
                return await self.map_profile(config, dict(id_token_claims), token_set)
            except OAuthError:
                pass
        return await super().resolve_profile(
            oauth_client=oauth_client,
            config=config,
            token_set=token_set,
            metadata=metadata,
            id_token_claims=id_token_claims,
        )


class MicrosoftOAuthStrategy(DefaultOAuthProviderStrategy):
    def __init__(
        self,
        *,
        scopes: list[str],
        disable_profile_photo: bool,
        profile_photo_size: int,
    ) -> None:
        self._scopes = list(scopes)
        self._disable_profile_photo = disable_profile_photo
        self._profile_photo_size = profile_photo_size

    async def refresh_token_response(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        config: OAuthProvider,
        token_set: OAuthTokenSet,
        token_endpoint: str,
    ) -> TokenResponsePayload:
        if token_set.refresh_token is None:
            msg = "oauth account does not have a refresh token"
            raise OAuthError(msg)

        token_params = dict(config.token_params)
        if "scope" not in token_params:
            token_params["scope"] = token_set.scope or serialize_scopes(self._scopes)

        if config.refresh_tokens is not None:
            raw_token = await config.refresh_tokens(oauth_client, token_set, token_params)
            return dict(raw_token)

        raw_token = await oauth_client.refresh_token(
            token_endpoint,
            refresh_token=token_set.refresh_token,
            **token_params,
        )
        return dict(raw_token)

    async def resolve_profile(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        config: OAuthProvider,
        token_set: OAuthTokenSet,
        metadata: ProviderMetadata,
        id_token_claims: RawProfile,
    ) -> OAuthUserInfo:
        if config.get_userinfo is not None:
            return await super().resolve_profile(
                oauth_client=oauth_client,
                config=config,
                token_set=token_set,
                metadata=metadata,
                id_token_claims=id_token_claims,
            )

        raw_profile = dict(id_token_claims)
        if token_set.access_token is not None:
            try:
                fetched_profile = await self._fetch_microsoft_profile(
                    oauth_client=oauth_client,
                    metadata=metadata,
                )
            except OAuthCallbackError:
                if not raw_profile:
                    raise
            else:
                raw_profile.update(fetched_profile)

        if not raw_profile:
            error_code = "user_info_missing"
            description = "provider did not return a usable profile"
            raise OAuthCallbackError(error_code, description)
        return await self.map_profile(config, raw_profile, token_set)

    async def _fetch_microsoft_profile(
        self,
        *,
        oauth_client: AuthlibOIDCClient,
        metadata: ProviderMetadata,
    ) -> RawProfile:
        userinfo_endpoint = coerce_optional_str(metadata.get("userinfo_endpoint"))
        if userinfo_endpoint is None:
            msg = "missing required provider metadata: userinfo_endpoint"
            error_code = "user_info_missing"
            raise OAuthCallbackError(error_code, msg)

        try:
            response = await oauth_client.get(userinfo_endpoint)
            response.raise_for_status()
        except Exception as exc:
            error_code = "user_info_missing"
            description = "failed to fetch provider user info"
            raise OAuthCallbackError(error_code, description) from exc

        profile = response.json()
        if not isinstance(profile, dict):
            msg = "provider user info missing profile data"
            error_code = "user_info_missing"
            raise OAuthCallbackError(error_code, msg)

        merged_profile = dict(profile)
        if self._disable_profile_photo:
            return merged_profile

        try:
            photo_response = await oauth_client.get(microsoft_profile_photo_url(self._profile_photo_size))
        except HTTPError:
            photo_response = None

        if photo_response is not None and photo_response.is_success:
            content_type = photo_response.headers.get("content-type", "image/jpeg")
            encoded = base64.b64encode(photo_response.content).decode("ascii")
            merged_profile["picture"] = f"data:{content_type};base64,{encoded}"
        return merged_profile
