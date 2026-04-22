from __future__ import annotations

import asyncio
import base64
import hashlib
import inspect
import re
import secrets
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from authlib.integrations.base_client.async_openid import AsyncOpenIDMixin
from authlib.integrations.httpx_client import AsyncOAuth2Client
from belgie_core.core.client import BelgieClient
from belgie_core.core.exceptions import ConfigurationError, InvalidStateError, OAuthError
from belgie_core.core.plugin import AuthenticatedProfile, PluginClient
from belgie_core.utils.crypto import generate_state_token
from cryptography.fernet import Fernet, InvalidToken
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_core.core.belgie import Belgie
    from belgie_core.core.settings import BelgieSettings
    from belgie_proto.core.oauth_account import OAuthAccountProtocol
    from belgie_proto.core.oauth_state import OAuthStateProtocol


type OAuthFlowIntent = Literal["signin", "link"]
type OAuthResponseMode = Literal["query", "form_post"]
type TokenEndpointAuthMethod = Literal["client_secret_basic", "client_secret_post", "none"]
type JSONValue = dict[str, object] | list[object] | str | int | float | bool | None
type RawProfile = dict[str, Any]
type UserInfoFetcher = Callable[..., Awaitable[Any]]
type TokenExchangeOverride = Callable[..., Awaitable[dict[str, Any]]]
type TokenRefreshOverride = Callable[..., Awaitable[dict[str, Any]]]
type ProfileMapper = Callable[..., Any]


@dataclass(slots=True, frozen=True, kw_only=True)
class OAuthTokenSet:
    access_token: str
    token_type: str | None
    refresh_token: str | None
    scope: str | None
    id_token: str | None
    expires_at: datetime | None
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_response(
        cls,
        token: dict[str, Any],
        *,
        existing_refresh_token: str | None = None,
    ) -> OAuthTokenSet:
        if not (access_token := token.get("access_token")):
            msg = "missing required field in token response: access_token"
            raise OAuthError(msg)

        refresh_token = token.get("refresh_token") or existing_refresh_token
        expires_at: datetime | None = None
        if isinstance(token.get("expires_at"), (int, float)):
            expires_at = datetime.fromtimestamp(token["expires_at"], tz=UTC)
        elif isinstance(token.get("expires_in"), (int, float)):
            expires_at = datetime.now(UTC) + timedelta(seconds=int(token["expires_in"]))

        return cls(
            access_token=str(access_token),
            token_type=_coerce_optional_str(token.get("token_type")),
            refresh_token=_coerce_optional_str(refresh_token),
            scope=_coerce_optional_str(token.get("scope")),
            id_token=_coerce_optional_str(token.get("id_token")),
            expires_at=expires_at,
            raw=dict(token),
        )


@dataclass(slots=True, frozen=True, kw_only=True)
class OAuthUserInfo:
    provider_account_id: str
    email: str | None
    email_verified: bool
    name: str | None = None
    image: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True, kw_only=True)
class OAuthLinkedAccount:
    id: UUID
    individual_id: UUID
    provider: str
    provider_account_id: str
    access_token: str | None
    refresh_token: str | None
    expires_at: datetime | None
    token_type: str | None
    scope: str | None
    id_token: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True, kw_only=True)
class ConsumedOAuthState:
    state: str
    provider: str | None
    individual_id: UUID | None
    code_verifier: str | None
    nonce: str | None
    intent: OAuthFlowIntent
    redirect_url: str | None
    error_redirect_url: str | None
    new_user_redirect_url: str | None
    payload: JSONValue
    request_sign_up: bool
    expires_at: datetime

    @classmethod
    def from_model(cls, oauth_state: OAuthStateProtocol) -> ConsumedOAuthState:
        return cls(
            state=oauth_state.state,
            provider=getattr(oauth_state, "provider", None),
            individual_id=oauth_state.individual_id,
            code_verifier=oauth_state.code_verifier,
            nonce=getattr(oauth_state, "nonce", None),
            intent=getattr(oauth_state, "intent", "signin"),
            redirect_url=oauth_state.redirect_url,
            error_redirect_url=getattr(oauth_state, "error_redirect_url", None),
            new_user_redirect_url=getattr(oauth_state, "new_user_redirect_url", None),
            payload=getattr(oauth_state, "payload", None),
            request_sign_up=getattr(oauth_state, "request_sign_up", False),
            expires_at=_normalize_datetime(oauth_state.expires_at) or datetime.now(UTC),
        )


class AuthlibOIDCClient(AsyncOpenIDMixin, AsyncOAuth2Client):
    def __init__(
        self,
        *,
        server_metadata_url: str | None = None,
        server_metadata: dict[str, Any] | None = None,
        discovery_headers: dict[str, str] | None = None,
        **kwargs: object,
    ) -> None:
        self._server_metadata_url = server_metadata_url
        self.server_metadata = dict(server_metadata or {})
        self._discovery_headers = dict(discovery_headers or {})
        super().__init__(**kwargs)

    @asynccontextmanager
    async def _get_session(self) -> AsyncIterator[AuthlibOIDCClient]:
        yield self

    async def load_server_metadata(self) -> dict[str, Any]:
        if self._server_metadata_url and "_loaded_at" not in self.server_metadata:
            response = await self.request(
                "GET",
                self._server_metadata_url,
                withhold_token=True,
                headers=self._discovery_headers or None,
            )
            response.raise_for_status()
            metadata = response.json()
            metadata["_loaded_at"] = time.time()
            self.server_metadata.update(metadata)
        return self.server_metadata


class OAuthProvider(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    provider_id: str
    client_id: str
    client_secret: SecretStr | None = None
    discovery_url: str | None = None
    issuer: str | None = None
    require_issuer_parameter_validation: bool = False
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    userinfo_endpoint: str | None = None
    jwks_uri: str | None = None
    scopes: list[str] = Field(default_factory=list)
    response_type: str = "code"
    response_mode: OAuthResponseMode | None = None
    prompt: str | None = None
    access_type: str | None = None
    use_pkce: bool = True
    code_challenge_method: Literal["S256", "plain"] = "S256"
    use_nonce: bool = True
    token_endpoint_auth_method: TokenEndpointAuthMethod = "client_secret_post"  # noqa: S105
    authorization_params: dict[str, str] = Field(default_factory=dict)
    token_params: dict[str, str] = Field(default_factory=dict)
    discovery_headers: dict[str, str] = Field(default_factory=dict)
    allow_sign_up: bool = True
    require_explicit_sign_up: bool = False
    encrypt_tokens: bool = False
    token_encryption_secret: SecretStr | None = None
    get_token: TokenExchangeOverride | None = None
    get_userinfo: UserInfoFetcher | None = None
    refresh_tokens: TokenRefreshOverride | None = None
    map_profile: ProfileMapper | None = None

    @field_validator("provider_id", "client_id")
    @classmethod
    def validate_non_empty(cls, value: str, info) -> str:  # noqa: ANN001
        if not value or not value.strip():
            msg = f"{info.field_name} must be a non-empty string"
            raise ValueError(msg)
        normalized = value.strip()
        if info.field_name == "provider_id" and re.fullmatch(r"[A-Za-z0-9_-]+", normalized) is None:
            msg = "provider_id may only contain letters, numbers, underscores, and hyphens"
            raise ValueError(msg)
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

    @model_validator(mode="after")
    def validate_endpoints(self) -> OAuthProvider:
        if self.discovery_url:
            return self
        if not self.authorization_endpoint or not self.token_endpoint:
            msg = "OAuthProvider requires discovery_url or both authorization_endpoint and token_endpoint"
            raise ValueError(msg)
        return self

    def __call__(self, belgie_settings: BelgieSettings) -> OAuthPlugin:
        return OAuthPlugin(belgie_settings, self)


class _OAuthTokenCodec:
    _PREFIX = "enc:v1:"

    def __init__(self, *, enabled: bool, secret: str | None) -> None:
        self.enabled = enabled
        self._fernet: Fernet | None = None
        if enabled:
            if not secret:
                msg = "token encryption requires a secret"
                raise ConfigurationError(msg)
            key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
            self._fernet = Fernet(key)

    def encode(self, value: str | None) -> str | None:
        if value is None or not self.enabled:
            return value
        if self._fernet is None:
            msg = "token encryption is not configured"
            raise ConfigurationError(msg)
        encrypted = self._fernet.encrypt(value.encode("utf-8")).decode("utf-8")
        return f"{self._PREFIX}{encrypted}"

    def decode(self, value: str | None) -> str | None:
        if value is None:
            return None
        if not value.startswith(self._PREFIX):
            return value
        if self._fernet is None:
            msg = "stored OAuth tokens are encrypted but decryption is not configured"
            raise OAuthError(msg)
        encrypted = value.removeprefix(self._PREFIX).encode("utf-8")
        try:
            return self._fernet.decrypt(encrypted).decode("utf-8")
        except InvalidToken as exc:
            msg = "failed to decrypt stored OAuth tokens"
            raise OAuthError(msg) from exc


@dataclass(slots=True, kw_only=True)
class OAuthClient:
    plugin: OAuthPlugin
    client: BelgieClient

    async def signin_url(  # noqa: PLR0913
        self,
        *,
        success_redirect_url: str | None = None,
        return_to: str | None = None,
        error_redirect_url: str | None = None,
        new_user_redirect_url: str | None = None,
        payload: JSONValue = None,
        scopes: list[str] | None = None,
        prompt: str | None = None,
        access_type: str | None = None,
        response_mode: OAuthResponseMode | None = None,
        authorization_params: dict[str, str] | None = None,
        request_sign_up: bool = False,
    ) -> str:
        redirect_target = success_redirect_url if success_redirect_url is not None else return_to
        return await self.plugin.start_authorization(
            self.client,
            intent="signin",
            redirect_url=redirect_target,
            error_redirect_url=error_redirect_url,
            new_user_redirect_url=new_user_redirect_url,
            payload=payload,
            scopes=scopes,
            prompt=prompt,
            access_type=access_type,
            response_mode=response_mode,
            authorization_params=authorization_params,
            request_sign_up=request_sign_up,
        )

    async def link_url(  # noqa: PLR0913
        self,
        *,
        individual_id: UUID,
        success_redirect_url: str | None = None,
        return_to: str | None = None,
        error_redirect_url: str | None = None,
        payload: JSONValue = None,
        scopes: list[str] | None = None,
        prompt: str | None = None,
        access_type: str | None = None,
        response_mode: OAuthResponseMode | None = None,
        authorization_params: dict[str, str] | None = None,
    ) -> str:
        redirect_target = success_redirect_url if success_redirect_url is not None else return_to
        return await self.plugin.start_authorization(
            self.client,
            intent="link",
            individual_id=individual_id,
            redirect_url=redirect_target,
            error_redirect_url=error_redirect_url,
            payload=payload,
            scopes=scopes,
            prompt=prompt,
            access_type=access_type,
            response_mode=response_mode,
            authorization_params=authorization_params,
        )

    async def list_accounts(self, *, individual_id: UUID) -> list[OAuthLinkedAccount]:
        return await self.plugin.list_accounts(self.client, individual_id=individual_id)

    async def get_access_token(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> str:
        return await self.plugin.get_access_token(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
        )

    async def refresh_account(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> OAuthLinkedAccount:
        return await self.plugin.refresh_account(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
        )

    async def account_info(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> OAuthUserInfo | None:
        return await self.plugin.account_info(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
            auto_refresh=auto_refresh,
        )

    async def unlink_account(
        self,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> bool:
        return await self.plugin.unlink_account(
            self.client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
        )


class OAuthPlugin(PluginClient):
    def __init__(
        self,
        belgie_settings: BelgieSettings,
        config: OAuthProvider,
        *,
        client_type: type[OAuthClient] = OAuthClient,
    ) -> None:
        self.config = config
        self._client_type = client_type
        self._redirect_uri = _build_provider_callback_url(
            belgie_settings.base_url,
            provider_id=self.provider_id,
        )
        self._resolve_client: Callable[..., OAuthClient] | None = None
        parsed_base_url = urlparse(belgie_settings.base_url)
        self._base_url_origin = (parsed_base_url.scheme.lower(), parsed_base_url.netloc.lower())
        self._metadata_cache: dict[str, Any] | None = None
        self._metadata_lock = asyncio.Lock()
        encryption_secret = (
            config.token_encryption_secret.get_secret_value()
            if config.token_encryption_secret is not None
            else belgie_settings.secret
        )
        self._token_codec = _OAuthTokenCodec(enabled=config.encrypt_tokens, secret=encryption_secret)

    @property
    def provider_id(self) -> str:
        return self.config.provider_id

    @property
    def redirect_uri(self) -> str:
        return self._redirect_uri

    def __call__(self, *args: object, **kwargs: object) -> OAuthClient:
        if self._resolve_client is None:
            msg = "OAuthPlugin dependency requires router initialization (call app.include_router(belgie.router) first)"
            raise RuntimeError(msg)
        return self._resolve_client(*args, **kwargs)

    def _ensure_dependency_resolver(self, belgie: Belgie) -> None:
        if self._resolve_client is not None:
            return

        type BelgieClientDep = BelgieClient

        def resolve_client(client: BelgieClientDep = Depends(belgie)) -> OAuthClient:  # noqa: B008
            return self._client_type(plugin=self, client=client)

        self._resolve_client = resolve_client
        self.__signature__ = inspect.signature(resolve_client)

    def normalize_redirect_target(self, target: str | None) -> str | None:
        if not target:
            return None

        parsed = urlparse(target)
        if not parsed.scheme and not parsed.netloc:
            if target.startswith("/") and not target.startswith("//"):
                return target
            return None

        if (parsed.scheme.lower(), parsed.netloc.lower()) != self._base_url_origin:
            return None

        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, ""))

    async def resolve_server_metadata(self) -> dict[str, Any]:
        if self._metadata_cache is not None:
            return dict(self._metadata_cache)

        async with self._metadata_lock:
            if self._metadata_cache is None:
                metadata = self._manual_metadata()
                if self.config.discovery_url is not None:
                    async with self._oauth_client(server_metadata=metadata) as oauth_client:
                        discovered = dict(await oauth_client.load_server_metadata())
                    discovered.update({key: value for key, value in metadata.items() if value is not None})
                    metadata = discovered
                self._metadata_cache = metadata
        return dict(self._metadata_cache)

    async def generate_authorization_url(  # noqa: PLR0913
        self,
        state: str,
        *,
        scopes: list[str] | None = None,
        prompt: str | None = None,
        access_type: str | None = None,
        response_mode: OAuthResponseMode | None = None,
        authorization_params: dict[str, str] | None = None,
        code_verifier: str | None = None,
        nonce: str | None = None,
    ) -> str:
        metadata = await self.resolve_server_metadata()
        authorization_endpoint = self._require_metadata_value(metadata, "authorization_endpoint")
        scope_text = _serialize_scopes(scopes or self.config.scopes)
        params = dict(self.config.authorization_params)
        if authorization_params:
            params.update(authorization_params)
        if prompt is not None:
            params["prompt"] = prompt
        elif self.config.prompt is not None:
            params["prompt"] = self.config.prompt
        if access_type is not None:
            params["access_type"] = access_type
        elif self.config.access_type is not None:
            params["access_type"] = self.config.access_type
        if response_mode is not None:
            params["response_mode"] = response_mode
        elif self.config.response_mode is not None:
            params["response_mode"] = self.config.response_mode
        if nonce is not None:
            params["nonce"] = nonce
        if code_verifier is not None and self.config.code_challenge_method == "plain":
            params["code_challenge"] = code_verifier
            params["code_challenge_method"] = "plain"

        async with self._oauth_client(server_metadata=metadata, scope=scope_text) as oauth_client:
            authorization_url, _ = oauth_client.create_authorization_url(
                authorization_endpoint,
                state=state,
                response_type=self.config.response_type,
                scope=scope_text,
                code_verifier=code_verifier,
                **params,
            )
        return authorization_url

    async def exchange_code_for_tokens(
        self,
        code: str,
        *,
        code_verifier: str | None = None,
    ) -> OAuthTokenSet:
        metadata = await self.resolve_server_metadata()
        token_endpoint = self._require_metadata_value(metadata, "token_endpoint")
        async with self._oauth_client(server_metadata=metadata) as oauth_client:
            if self.config.get_token is not None:
                token = await self.config.get_token(
                    oauth_client,
                    code,
                    dict(self.config.token_params),
                    code_verifier,
                )
            else:
                token = await oauth_client.fetch_token(
                    token_endpoint,
                    code=code,
                    grant_type="authorization_code",
                    redirect_uri=self.redirect_uri,
                    code_verifier=code_verifier,
                    **self.config.token_params,
                )
        return OAuthTokenSet.from_response(dict(token))

    async def list_accounts(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
    ) -> list[OAuthLinkedAccount]:
        accounts = await client.list_oauth_accounts(individual_id=individual_id, provider=self.provider_id)
        return [self._linked_account_snapshot(account) for account in accounts]

    async def get_access_token(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> str:
        account = await self._get_linked_account(
            client,
            individual_id=individual_id,
            provider_account_id=provider_account_id,
        )
        if account is None:
            msg = "oauth account not found"
            raise OAuthError(msg)

        if auto_refresh and self._should_refresh(account):
            account = await self.refresh_account(
                client,
                individual_id=individual_id,
                provider_account_id=provider_account_id,
            )

        if account.access_token is None:
            msg = "oauth account does not have an access token"
            raise OAuthError(msg)
        return account.access_token

    async def refresh_account(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> OAuthLinkedAccount:
        record = await client.get_oauth_account_for_individual(
            individual_id=individual_id,
            provider=self.provider_id,
            provider_account_id=provider_account_id,
        )
        if record is None:
            msg = "oauth account not found"
            raise OAuthError(msg)

        account = self._linked_account_snapshot(record)
        if account.refresh_token is None:
            msg = "oauth account does not have a refresh token"
            raise OAuthError(msg)

        metadata = await self.resolve_server_metadata()
        token_endpoint = self._require_metadata_value(metadata, "token_endpoint")
        token_params = dict(self.config.token_params)
        async with self._oauth_client(server_metadata=metadata, token=self._token_payload(account)) as oauth_client:
            if self.config.refresh_tokens is not None:
                raw_token = await self.config.refresh_tokens(oauth_client, account, token_params)
            else:
                raw_token = await oauth_client.refresh_token(
                    token_endpoint,
                    refresh_token=account.refresh_token,
                    **token_params,
                )

        token_set = OAuthTokenSet.from_response(dict(raw_token), existing_refresh_token=account.refresh_token)
        updated = await client.update_oauth_account_by_id(record.id, **self._encoded_token_updates(token_set))
        if updated is None:
            msg = "failed to update refreshed oauth account"
            raise OAuthError(msg)
        return self._linked_account_snapshot(updated)

    async def account_info(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
        auto_refresh: bool = True,
    ) -> OAuthUserInfo | None:
        record = await client.get_oauth_account_for_individual(
            individual_id=individual_id,
            provider=self.provider_id,
            provider_account_id=provider_account_id,
        )
        if record is None:
            return None

        account = self._linked_account_snapshot(record)
        if auto_refresh and self._should_refresh(account):
            account = await self.refresh_account(
                client,
                individual_id=individual_id,
                provider_account_id=provider_account_id,
            )
        if account.access_token is None:
            return None

        metadata = await self.resolve_server_metadata()
        token_set = OAuthTokenSet(
            access_token=account.access_token,
            token_type=account.token_type,
            refresh_token=account.refresh_token,
            scope=account.scope,
            id_token=account.id_token,
            expires_at=account.expires_at,
            raw=self._token_payload(account),
        )
        async with self._oauth_client(server_metadata=metadata, token=self._token_payload(account)) as oauth_client:
            return await self._fetch_provider_profile(oauth_client, token_set)

    async def unlink_account(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> bool:
        return await client.unlink_oauth_account(
            individual_id=individual_id,
            provider=self.provider_id,
            provider_account_id=provider_account_id,
        )

    async def start_authorization(  # noqa: PLR0913
        self,
        client: BelgieClient,
        *,
        intent: OAuthFlowIntent,
        individual_id: UUID | None = None,
        redirect_url: str | None = None,
        error_redirect_url: str | None = None,
        new_user_redirect_url: str | None = None,
        payload: JSONValue = None,
        scopes: list[str] | None = None,
        prompt: str | None = None,
        access_type: str | None = None,
        response_mode: OAuthResponseMode | None = None,
        authorization_params: dict[str, str] | None = None,
        request_sign_up: bool = False,
    ) -> str:
        state = generate_state_token()
        code_verifier = _generate_code_verifier() if self.config.use_pkce else None
        nonce = generate_state_token() if self._should_use_nonce(scopes) else None
        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        normalized_redirect = self.normalize_redirect_target(redirect_url)
        normalized_error_redirect = self.normalize_redirect_target(error_redirect_url)
        normalized_new_user_redirect = self.normalize_redirect_target(new_user_redirect_url)
        await client.adapter.create_oauth_state(
            client.db,
            state=state,
            expires_at=expires_at.replace(tzinfo=None),
            provider=self.provider_id,
            code_verifier=code_verifier,
            nonce=nonce,
            intent=intent,
            redirect_url=normalized_redirect,
            error_redirect_url=normalized_error_redirect,
            new_user_redirect_url=normalized_new_user_redirect,
            payload=payload,
            request_sign_up=request_sign_up,
            individual_id=individual_id,
        )
        return await self.generate_authorization_url(
            state,
            scopes=scopes,
            prompt=prompt,
            access_type=access_type,
            response_mode=response_mode,
            authorization_params=authorization_params,
            code_verifier=code_verifier,
            nonce=nonce,
        )

    def router(self, belgie: Belgie) -> APIRouter:  # noqa: C901
        self._ensure_dependency_resolver(belgie)
        router = APIRouter(prefix=f"/provider/{self.provider_id}", tags=["auth", "oauth"])

        @router.api_route("/callback", methods=["GET", "POST"])
        async def callback(
            request: Request,
            client: BelgieClient = Depends(belgie),  # noqa: B008
        ) -> RedirectResponse:
            consumed_state: ConsumedOAuthState | None = None
            try:
                callback_params = await self._extract_callback_params(request)
                state = callback_params.get("state")
                if not state:
                    msg = "missing OAuth state"
                    raise InvalidStateError(msg)  # noqa: TRY301

                oauth_state = await client.adapter.get_oauth_state(client.db, state)
                if oauth_state is None:
                    msg = "Invalid OAuth state"
                    raise InvalidStateError(msg)  # noqa: TRY301

                consumed_state = ConsumedOAuthState.from_model(oauth_state)
                if consumed_state.provider and consumed_state.provider != self.provider_id:
                    msg = "OAuth state provider mismatch"
                    raise InvalidStateError(msg)  # noqa: TRY301
                if consumed_state.expires_at <= datetime.now(UTC):
                    await client.adapter.delete_oauth_state(client.db, state)
                    msg = "OAuth state expired"
                    raise InvalidStateError(msg)  # noqa: TRY301

                metadata = await self.resolve_server_metadata()
                self._validate_issuer_parameter(callback_params.get("iss"), metadata)
                await client.adapter.delete_oauth_state(client.db, state)

                request.state.oauth_state = consumed_state
                request.state.oauth_payload = consumed_state.payload

                if callback_params.get("error"):
                    description = callback_params.get("error_description") or callback_params["error"]
                    raise OAuthError(description)  # noqa: TRY301

                if not (code := callback_params.get("code")):
                    msg = "missing OAuth authorization code"
                    raise OAuthError(msg)  # noqa: TRY301

                token_set = await self.exchange_code_for_tokens(code, code_verifier=consumed_state.code_verifier)

                async with self._oauth_client(server_metadata=metadata, token=token_set.raw) as oauth_client:
                    provider_user = await self._fetch_provider_profile(
                        oauth_client,
                        token_set,
                        nonce=consumed_state.nonce,
                    )

                if consumed_state.intent == "link":
                    response = await self._complete_link_flow(
                        belgie,
                        client,
                        request,
                        consumed_state,
                        provider_user,
                        token_set,
                    )
                else:
                    response = await self._complete_signin_flow(
                        belgie,
                        client,
                        request,
                        consumed_state,
                        provider_user,
                        token_set,
                    )
                return response  # noqa: TRY300
            except (InvalidStateError, OAuthError):
                if consumed_state and consumed_state.error_redirect_url:
                    return RedirectResponse(
                        url=_append_query_params(
                            consumed_state.error_redirect_url,
                            {"error": "oauth_callback_failed"},
                        ),
                        status_code=status.HTTP_302_FOUND,
                    )
                raise

        return router

    def public(self, belgie: Belgie) -> APIRouter:  # noqa: ARG002
        return APIRouter()

    async def _complete_signin_flow(  # noqa: C901, PLR0913
        self,
        belgie: Belgie,
        client: BelgieClient,
        request: Request,
        oauth_state: ConsumedOAuthState,
        provider_user: OAuthUserInfo,
        token_set: OAuthTokenSet,
    ) -> RedirectResponse:
        existing_account = await client.get_oauth_account(
            provider=self.provider_id,
            provider_account_id=provider_user.provider_account_id,
        )

        if existing_account is not None:
            individual = await client.adapter.get_individual_by_id(client.db, existing_account.individual_id)
            if individual is None:
                msg = "linked individual not found"
                raise OAuthError(msg)
            session = await client.sign_in_individual(individual, request=request)
            updated_account = await client.update_oauth_account_by_id(
                existing_account.id,
                **self._encoded_token_updates(token_set),
            )
            if updated_account is None:
                msg = "failed to update linked oauth account"
                raise OAuthError(msg)
            await belgie.after_authenticate(
                client=client,
                request=request,
                individual=individual,
                profile=AuthenticatedProfile(
                    provider=self.provider_id,
                    provider_account_id=provider_user.provider_account_id,
                    email=provider_user.email or individual.email,
                    email_verified=provider_user.email_verified,
                    name=provider_user.name,
                    image=provider_user.image,
                ),
            )
            response = RedirectResponse(
                url=oauth_state.redirect_url or belgie.settings.urls.signin_redirect,
                status_code=status.HTTP_302_FOUND,
            )
            return client.create_session_cookie(session, response)

        if provider_user.email is None:
            msg = "provider user info missing email"
            raise OAuthError(msg)

        existing_individual = await client.adapter.get_individual_by_email(client.db, provider_user.email)
        if existing_individual is None:
            if not self.config.allow_sign_up:
                msg = "sign up is disabled for this provider"
                raise OAuthError(msg)
            if self.config.require_explicit_sign_up and not oauth_state.request_sign_up:
                msg = "sign up requires an explicit request"
                raise OAuthError(msg)

        verified_at = datetime.now(UTC) if provider_user.email_verified else None
        individual, created = await client.get_or_create_individual(
            provider_user.email,
            name=provider_user.name,
            image=provider_user.image,
            email_verified_at=verified_at,
        )
        session = await client.sign_in_individual(individual, request=request)
        if created and client.after_sign_up is not None:
            await client.after_sign_up(
                client=client,
                request=request,
                individual=individual,
            )

        await client.upsert_oauth_account(
            individual_id=individual.id,
            provider=self.provider_id,
            provider_account_id=provider_user.provider_account_id,
            **self._encoded_token_updates(token_set),
        )
        await belgie.after_authenticate(
            client=client,
            request=request,
            individual=individual,
            profile=AuthenticatedProfile(
                provider=self.provider_id,
                provider_account_id=provider_user.provider_account_id,
                email=provider_user.email,
                email_verified=provider_user.email_verified,
                name=provider_user.name,
                image=provider_user.image,
            ),
        )

        redirect_url = belgie.settings.urls.signin_redirect
        if created and oauth_state.new_user_redirect_url:
            redirect_url = oauth_state.new_user_redirect_url
        elif oauth_state.redirect_url:
            redirect_url = oauth_state.redirect_url

        response = RedirectResponse(
            url=redirect_url,
            status_code=status.HTTP_302_FOUND,
        )
        return client.create_session_cookie(session, response)

    async def _complete_link_flow(  # noqa: PLR0913
        self,
        belgie: Belgie,
        client: BelgieClient,
        request: Request,  # noqa: ARG002
        oauth_state: ConsumedOAuthState,
        provider_user: OAuthUserInfo,
        token_set: OAuthTokenSet,
    ) -> RedirectResponse:
        if oauth_state.individual_id is None:
            msg = "link flow is missing the initiating individual"
            raise OAuthError(msg)

        if await client.adapter.get_individual_by_id(client.db, oauth_state.individual_id) is None:
            msg = "initiating individual not found"
            raise OAuthError(msg)

        existing_account = await client.get_oauth_account(
            provider=self.provider_id,
            provider_account_id=provider_user.provider_account_id,
        )
        if existing_account is not None and existing_account.individual_id != oauth_state.individual_id:
            msg = "oauth account already linked to another individual"
            raise OAuthError(msg)

        await client.upsert_oauth_account(
            individual_id=oauth_state.individual_id,
            provider=self.provider_id,
            provider_account_id=provider_user.provider_account_id,
            **self._encoded_token_updates(token_set),
        )

        return RedirectResponse(
            url=oauth_state.redirect_url or belgie.settings.urls.signin_redirect,
            status_code=status.HTTP_302_FOUND,
        )

    async def _extract_callback_params(self, request: Request) -> dict[str, str]:
        params = dict(request.query_params)
        if request.method.upper() == "POST":
            form = await request.form()
            params.update({key: str(value) for key, value in form.items()})
        return params

    async def _fetch_provider_profile(
        self,
        oauth_client: AuthlibOIDCClient,
        token_set: OAuthTokenSet,
        *,
        nonce: str | None = None,
    ) -> OAuthUserInfo:
        raw_profile: dict[str, Any] = {}
        if token_set.id_token is not None and nonce is not None:
            try:
                id_token_claims = await oauth_client.parse_id_token(token_set.raw, nonce=nonce)
                raw_profile.update(dict(id_token_claims))
            except Exception as exc:
                msg = "failed to validate provider id token"
                raise OAuthError(msg) from exc

        fetched_profile = await self._fetch_userinfo(oauth_client, token_set)
        if isinstance(fetched_profile, OAuthUserInfo):
            if raw_profile:
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
            return fetched_profile
        if fetched_profile is not None:
            raw_profile.update(fetched_profile)

        if not raw_profile:
            msg = "provider did not return a usable profile"
            raise OAuthError(msg)
        return self._map_profile(raw_profile, token_set)

    async def _fetch_userinfo(
        self,
        oauth_client: AuthlibOIDCClient,
        token_set: OAuthTokenSet,
    ) -> RawProfile | OAuthUserInfo | None:
        metadata = await oauth_client.load_server_metadata()
        if self.config.get_userinfo is not None:
            return await self.config.get_userinfo(oauth_client, token_set, metadata)
        if metadata.get("userinfo_endpoint") is None:
            return None
        try:
            profile = await oauth_client.userinfo()
        except Exception as exc:
            msg = "failed to fetch provider user info"
            raise OAuthError(msg) from exc
        return dict(profile)

    async def _get_linked_account(
        self,
        client: BelgieClient,
        *,
        individual_id: UUID,
        provider_account_id: str,
    ) -> OAuthLinkedAccount | None:
        record = await client.get_oauth_account_for_individual(
            individual_id=individual_id,
            provider=self.provider_id,
            provider_account_id=provider_account_id,
        )
        if record is None:
            return None
        return self._linked_account_snapshot(record)

    def _map_profile(self, raw_profile: RawProfile, token_set: OAuthTokenSet) -> OAuthUserInfo:
        if self.config.map_profile is not None:
            return self.config.map_profile(raw_profile, token_set)

        provider_account_id = _coerce_optional_str(raw_profile.get("sub")) or _coerce_optional_str(
            raw_profile.get("id"),
        )
        if provider_account_id is None:
            msg = "provider user info missing subject identifier"
            raise OAuthError(msg)

        email_verified = False
        if isinstance(raw_profile.get("email_verified"), bool):
            email_verified = raw_profile["email_verified"]
        elif isinstance(raw_profile.get("verified_email"), bool):
            email_verified = raw_profile["verified_email"]

        return OAuthUserInfo(
            provider_account_id=provider_account_id,
            email=_coerce_optional_str(raw_profile.get("email")),
            email_verified=email_verified,
            name=_coerce_optional_str(raw_profile.get("name")),
            image=_coerce_optional_str(raw_profile.get("picture"))
            or _coerce_optional_str(raw_profile.get("avatar_url")),
            raw=dict(raw_profile),
        )

    def _manual_metadata(self) -> dict[str, Any]:
        return {
            "authorization_endpoint": self.config.authorization_endpoint,
            "token_endpoint": self.config.token_endpoint,
            "userinfo_endpoint": self.config.userinfo_endpoint,
            "jwks_uri": self.config.jwks_uri,
            "issuer": self.config.issuer,
        }

    def _oauth_client(
        self,
        *,
        server_metadata: dict[str, Any],
        scope: str | None = None,
        token: dict[str, Any] | None = None,
    ) -> AuthlibOIDCClient:
        return AuthlibOIDCClient(
            client_id=self.config.client_id,
            client_secret=self.config.client_secret.get_secret_value() if self.config.client_secret else None,
            token_endpoint_auth_method=self.config.token_endpoint_auth_method,
            scope=scope,
            redirect_uri=self.redirect_uri,
            token=token,
            server_metadata_url=self.config.discovery_url,
            server_metadata=server_metadata,
            discovery_headers=self.config.discovery_headers,
            code_challenge_method=self.config.code_challenge_method,
        )

    def _require_metadata_value(self, metadata: dict[str, Any], key: str) -> str:
        value = metadata.get(key)
        if not value:
            msg = f"missing required provider metadata: {key}"
            raise ConfigurationError(msg)
        return str(value)

    def _should_use_nonce(self, scopes: list[str] | None) -> bool:
        effective_scopes = scopes or self.config.scopes
        return self.config.use_nonce and "openid" in effective_scopes

    def _validate_issuer_parameter(self, issuer: str | None, metadata: dict[str, Any]) -> None:
        expected_issuer = self.config.issuer or _coerce_optional_str(metadata.get("issuer"))
        if expected_issuer is None:
            return
        if issuer is None:
            if self.config.require_issuer_parameter_validation:
                msg = "missing OAuth issuer parameter"
                raise OAuthError(msg)
            return
        if issuer != expected_issuer:
            msg = "OAuth issuer mismatch"
            raise OAuthError(msg)

    def _encoded_token_updates(self, token_set: OAuthTokenSet) -> dict[str, Any]:
        return {
            "access_token": self._token_codec.encode(token_set.access_token),
            "refresh_token": self._token_codec.encode(token_set.refresh_token),
            "expires_at": token_set.expires_at,
            "scope": token_set.scope,
            "token_type": token_set.token_type,
            "id_token": self._token_codec.encode(token_set.id_token),
        }

    def _linked_account_snapshot(self, account: OAuthAccountProtocol) -> OAuthLinkedAccount:
        return OAuthLinkedAccount(
            id=account.id,
            individual_id=account.individual_id,
            provider=account.provider,
            provider_account_id=account.provider_account_id,
            access_token=self._token_codec.decode(account.access_token),
            refresh_token=self._token_codec.decode(account.refresh_token),
            expires_at=_normalize_datetime(account.expires_at),
            token_type=account.token_type,
            scope=account.scope,
            id_token=self._token_codec.decode(account.id_token),
            created_at=_normalize_datetime(account.created_at) or datetime.now(UTC),
            updated_at=_normalize_datetime(account.updated_at) or datetime.now(UTC),
        )

    def _should_refresh(self, account: OAuthLinkedAccount) -> bool:
        if account.expires_at is None or account.refresh_token is None:
            return False
        return account.expires_at <= datetime.now(UTC) + timedelta(seconds=30)

    def _token_payload(self, account: OAuthLinkedAccount) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "access_token": account.access_token,
        }
        if account.refresh_token is not None:
            payload["refresh_token"] = account.refresh_token
        if account.id_token is not None:
            payload["id_token"] = account.id_token
        if account.token_type is not None:
            payload["token_type"] = account.token_type
        if account.scope is not None:
            payload["scope"] = account.scope
        if account.expires_at is not None:
            payload["expires_at"] = int(account.expires_at.timestamp())
        return payload


def _build_provider_callback_url(base_url: str, *, provider_id: str) -> str:
    parsed = urlparse(base_url)
    path = parsed.path.rstrip("/")
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            f"{path}/auth/provider/{provider_id}/callback",
            "",
            "",
            "",
        ),
    )


def _append_query_params(url: str, params: dict[str, str]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update(params)
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment,
        ),
    )


def _serialize_scopes(scopes: list[str]) -> str:
    return " ".join(dict.fromkeys(scopes))


def _generate_code_verifier() -> str:
    return secrets.token_urlsafe(64)


def _coerce_optional_str(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _normalize_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "ConsumedOAuthState",
    "OAuthClient",
    "OAuthLinkedAccount",
    "OAuthPlugin",
    "OAuthProvider",
    "OAuthTokenSet",
    "OAuthUserInfo",
]
