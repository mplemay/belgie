from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from authlib.integrations.base_client.async_openid import AsyncOpenIDMixin
from authlib.integrations.httpx_client import AsyncOAuth2Client
from authlib.oidc.core import CodeIDToken, ImplicitIDToken, UserInfo
from belgie_core.core.exceptions import ConfigurationError
from joserfc import jwt
from joserfc.errors import InvalidClaimError, InvalidKeyIdError
from joserfc.jwk import KeySet

from belgie_oauth._errors import OAuthCallbackError
from belgie_oauth._helpers import coerce_optional_str, serialize_scopes
from belgie_oauth._models import OAuthTokenSet, OAuthUserInfo
from belgie_oauth._strategy import DefaultOAuthProviderStrategy, OAuthProviderStrategy

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from belgie_oauth._config import OAuthProvider


type IDTokenClaimsClass = type[CodeIDToken | ImplicitIDToken]


class AuthlibOIDCClient(AsyncOpenIDMixin, AsyncOAuth2Client):
    def __init__(
        self,
        *,
        server_metadata_url: str | None = None,
        server_metadata: dict[str, Any] | None = None,
        discovery_headers: dict[str, str] | None = None,
        accepted_client_ids: tuple[str, ...] | None = None,
        **kwargs: object,
    ) -> None:
        self._server_metadata_url = server_metadata_url
        self.server_metadata = dict(server_metadata or {})
        self._discovery_headers = dict(discovery_headers or {})
        self._accepted_client_ids = accepted_client_ids
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

    async def parse_id_token(
        self,
        token: dict[str, Any],
        nonce: str,
        claims_options: dict[str, Any] | None = None,
        claims_cls: IDTokenClaimsClass | None = None,
        leeway: int = 120,
    ) -> UserInfo:
        if "id_token" not in token:
            msg = 'Missing "id_token" in token payload'
            error_code = "oauth_code_verification_failed"
            raise OAuthCallbackError(error_code, msg)

        accepted_client_ids = self._accepted_client_ids or (self.client_id,)
        claims_params: dict[str, Any] = {
            "nonce": nonce,
            "client_id": accepted_client_ids[0],
            "accepted_client_ids": accepted_client_ids,
        }
        if "access_token" in token:
            claims_params["access_token"] = token["access_token"]
            if claims_cls is None:
                claims_cls = BelgieCodeIDToken
        elif claims_cls is None:
            claims_cls = BelgieImplicitIDToken

        metadata = await self.load_server_metadata()
        resolved_claims_options = dict(claims_options or {})
        if "iss" not in resolved_claims_options and "issuer" in metadata:
            resolved_claims_options["iss"] = {"values": [metadata["issuer"]]}
        if "aud" not in resolved_claims_options:
            resolved_claims_options["aud"] = {"values": list(accepted_client_ids)}

        alg_values = metadata.get("id_token_signing_alg_values_supported")
        if not alg_values:
            alg_values = ["RS256"]

        jwks = await self.fetch_jwk_set()
        key_set = KeySet.import_key_set(jwks)
        try:
            decoded = jwt.decode(
                token["id_token"],
                key=key_set,
                algorithms=alg_values,
            )
        except InvalidKeyIdError:
            jwks = await self.fetch_jwk_set(force=True)
            key_set = KeySet.import_key_set(jwks)
            decoded = jwt.decode(
                token["id_token"],
                key=key_set,
                algorithms=alg_values,
            )

        claims = claims_cls(
            decoded.claims,
            decoded.header,
            resolved_claims_options,
            claims_params,
        )
        if claims.get("nonce_supported") is False:
            claims.params["nonce"] = None
        claims.validate(leeway=leeway)
        return UserInfo(claims)


class BelgieIDTokenMixin:
    def validate_azp(self) -> None:
        accepted_client_ids = tuple(self.params.get("accepted_client_ids") or ())
        if not accepted_client_ids:
            super().validate_azp()
            return

        azp = self.get("azp")
        if azp is not None and azp not in accepted_client_ids:
            claim_name = "azp"
            raise InvalidClaimError(claim_name)
        return


class BelgieCodeIDToken(BelgieIDTokenMixin, CodeIDToken):
    pass


class BelgieImplicitIDToken(BelgieIDTokenMixin, ImplicitIDToken):
    pass


class OAuthTransport:
    def __init__(self, config: OAuthProvider, *, redirect_uri: str) -> None:
        self.config = config
        self.redirect_uri = redirect_uri
        self._strategy: OAuthProviderStrategy = config.strategy or DefaultOAuthProviderStrategy()
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
        params = self._strategy.build_authorization_params(
            config=self.config,
            prompt=prompt,
            access_type=access_type,
            response_mode=response_mode,
            authorization_params=authorization_params,
            code_verifier=code_verifier,
            nonce=nonce,
        )

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
            token = await self._strategy.exchange_code_for_tokens(
                oauth_client=oauth_client,
                config=self.config,
                code=code,
                redirect_uri=self.redirect_uri,
                code_verifier=code_verifier,
                token_endpoint=token_endpoint,
            )
        return OAuthTokenSet.from_response(dict(token))

    async def refresh_token_set(self, token_set: OAuthTokenSet) -> OAuthTokenSet:
        metadata = await self.resolve_server_metadata()
        token_endpoint = self.require_metadata_value(metadata, "token_endpoint")
        async with self._oauth_client(server_metadata=metadata, token=token_set.raw) as oauth_client:
            raw_token = await self._strategy.refresh_token_response(
                oauth_client=oauth_client,
                config=self.config,
                token_set=token_set,
                token_endpoint=token_endpoint,
            )
        return OAuthTokenSet.from_response(dict(raw_token), existing=token_set)

    async def fetch_provider_profile(
        self,
        token_set: OAuthTokenSet,
        *,
        nonce: str | None = None,
    ) -> OAuthUserInfo:
        metadata = await self.resolve_server_metadata()
        id_token_claims: dict[str, Any] = {}
        async with self._oauth_client(server_metadata=metadata, token=token_set.raw) as oauth_client:
            if token_set.id_token is not None and nonce is not None:
                try:
                    parsed_id_token = await oauth_client.parse_id_token(token_set.raw, nonce=nonce)
                    id_token_claims = dict(parsed_id_token)
                except Exception as exc:
                    error_code = "oauth_code_verification_failed"
                    description = "failed to validate provider id token"
                    raise OAuthCallbackError(
                        error_code,
                        description,
                    ) from exc
            return await self._strategy.resolve_profile(
                oauth_client=oauth_client,
                config=self.config,
                token_set=token_set,
                metadata=metadata,
                id_token_claims=id_token_claims,
            )

    def validate_issuer_parameter(self, issuer: str | None, metadata: dict[str, Any]) -> None:
        expected_issuer = self.config.issuer or coerce_optional_str(metadata.get("issuer"))
        if expected_issuer is None:
            return
        if issuer is None:
            if self.config.require_issuer_parameter_validation:
                error_code = "issuer_missing"
                description = "missing OAuth issuer parameter"
                raise OAuthCallbackError(error_code, description)
            return
        if issuer != expected_issuer:
            error_code = "issuer_mismatch"
            description = "OAuth issuer mismatch"
            raise OAuthCallbackError(error_code, description)

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
            client_id=self.config.primary_client_id,
            client_secret=self.config.client_secret.get_secret_value() if self.config.client_secret else None,
            token_endpoint_auth_method=self.config.token_endpoint_auth_method,
            scope=scope,
            redirect_uri=self.redirect_uri,
            token=token,
            server_metadata_url=self.config.discovery_url,
            server_metadata=server_metadata,
            discovery_headers=self.config.discovery_headers,
            accepted_client_ids=self.config.accepted_client_ids,
            code_challenge_method=self.config.code_challenge_method,
        )
