from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from authlib.integrations.base_client.async_openid import AsyncOpenIDMixin
from authlib.integrations.httpx_client import AsyncOAuth2Client
from belgie_core.core.exceptions import ConfigurationError, OAuthError

from belgie_oauth._helpers import coerce_optional_str, serialize_scopes
from belgie_oauth._models import OAuthTokenSet, OAuthUserInfo, RawProfile

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from belgie_oauth._config import OAuthProvider


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


class OAuthTransport:
    def __init__(self, config: OAuthProvider, *, redirect_uri: str) -> None:
        self.config = config
        self.redirect_uri = redirect_uri
        self._metadata_cache: dict[str, Any] | None = None
        self._metadata_lock = asyncio.Lock()

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
        response_mode: str | None = None,
        authorization_params: dict[str, str] | None = None,
        code_verifier: str | None = None,
        nonce: str | None = None,
    ) -> str:
        metadata = await self.resolve_server_metadata()
        authorization_endpoint = self.require_metadata_value(metadata, "authorization_endpoint")
        scope_text = serialize_scopes(scopes or self.config.scopes)
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
        token_endpoint = self.require_metadata_value(metadata, "token_endpoint")
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

    async def refresh_token_set(self, token_set: OAuthTokenSet) -> OAuthTokenSet:
        metadata = await self.resolve_server_metadata()
        token_endpoint = self.require_metadata_value(metadata, "token_endpoint")
        token_params = dict(self.config.token_params)
        async with self._oauth_client(server_metadata=metadata, token=token_set.raw) as oauth_client:
            if self.config.refresh_tokens is not None:
                raw_token = await self.config.refresh_tokens(oauth_client, token_set, token_params)
            else:
                if token_set.refresh_token is None:
                    msg = "oauth account does not have a refresh token"
                    raise OAuthError(msg)
                raw_token = await oauth_client.refresh_token(
                    token_endpoint,
                    refresh_token=token_set.refresh_token,
                    **token_params,
                )
        return OAuthTokenSet.from_response(dict(raw_token), existing=token_set)

    async def fetch_provider_profile(
        self,
        token_set: OAuthTokenSet,
        *,
        nonce: str | None = None,
    ) -> OAuthUserInfo:
        metadata = await self.resolve_server_metadata()
        raw_profile: dict[str, Any] = {}
        async with self._oauth_client(server_metadata=metadata, token=token_set.raw) as oauth_client:
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
        return self.map_profile(raw_profile, token_set)

    def map_profile(self, raw_profile: RawProfile, token_set: OAuthTokenSet) -> OAuthUserInfo:
        if self.config.map_profile is not None:
            return self.config.map_profile(raw_profile, token_set)

        provider_account_id = coerce_optional_str(raw_profile.get("sub")) or coerce_optional_str(raw_profile.get("id"))
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
            email=coerce_optional_str(raw_profile.get("email")),
            email_verified=email_verified,
            name=coerce_optional_str(raw_profile.get("name")),
            image=coerce_optional_str(raw_profile.get("picture")) or coerce_optional_str(raw_profile.get("avatar_url")),
            raw=dict(raw_profile),
        )

    def validate_issuer_parameter(self, issuer: str | None, metadata: dict[str, Any]) -> None:
        expected_issuer = self.config.issuer or coerce_optional_str(metadata.get("issuer"))
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

    def token_payload(self, token_set: OAuthTokenSet) -> dict[str, Any]:
        payload = dict(token_set.raw)
        payload["access_token"] = token_set.access_token
        if token_set.refresh_token is not None:
            payload["refresh_token"] = token_set.refresh_token
        if token_set.id_token is not None:
            payload["id_token"] = token_set.id_token
        if token_set.token_type is not None:
            payload["token_type"] = token_set.token_type
        if token_set.scope is not None:
            payload["scope"] = token_set.scope
        if token_set.access_token_expires_at is not None:
            payload["expires_at"] = int(token_set.access_token_expires_at.timestamp())
        if token_set.refresh_token_expires_at is not None:
            payload["refresh_token_expires_at"] = int(token_set.refresh_token_expires_at.timestamp())
        return payload

    def should_use_nonce(self, scopes: list[str] | None) -> bool:
        effective_scopes = scopes or self.config.scopes
        return self.config.use_nonce and "openid" in effective_scopes

    def require_metadata_value(self, metadata: dict[str, Any], key: str) -> str:
        value = metadata.get(key)
        if not value:
            msg = f"missing required provider metadata: {key}"
            raise ConfigurationError(msg)
        return str(value)

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
