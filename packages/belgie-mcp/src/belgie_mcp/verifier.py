import logging
from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any, Literal

import jwt
from belgie_oauth_server.provider import SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.utils import join_url
from belgie_oauth_server.verifier import verify_local_access_token
from httpx import AsyncClient, HTTPError, Limits, Timeout
from jwt import DecodeError, InvalidTokenError, PyJWKSet, PyJWKSetError
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.shared.auth_utils import check_resource_allowed, resource_url_from_server_url
from pydantic import AnyHttpUrl

logger = logging.getLogger(__name__)

_HTTP_OK = 200
_JWKS_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True, slots=True, kw_only=True)
class _TokenVerification:
    status: Literal["not_found", "rejected", "verified"]
    token: AccessToken | None = None


class BelgieOAuthTokenVerifier(TokenVerifier):
    def __init__(  # noqa: PLR0913
        self,
        introspection_endpoint: str,
        server_url: str,
        *,
        provider_resolver: Callable[[], SimpleOAuthProvider | None] | None = None,
        validate_resource: bool = False,
        introspection_client_id: str | None = None,
        introspection_client_secret: str | None = None,
        jwt_issuer: str | None = None,
        jwks_endpoint: str | None = None,
        jwt_algorithm: str = "RS256",
    ) -> None:
        self.introspection_endpoint = str(introspection_endpoint)
        self.server_url = str(server_url)
        self.provider_resolver = provider_resolver
        self.validate_resource = validate_resource
        self.introspection_client_id = introspection_client_id
        self.introspection_client_secret = introspection_client_secret
        self.jwt_issuer = None if jwt_issuer is None else str(jwt_issuer)
        self.jwks_endpoint = None if jwks_endpoint is None else str(jwks_endpoint)
        self.jwt_algorithm = jwt_algorithm
        self.resource_url = resource_url_from_server_url(self.server_url)
        self._jwks: PyJWKSet | None = None
        self._jwks_fetched_at: float | None = None

    async def verify_token(self, token: str) -> AccessToken | None:
        if self.provider_resolver is not None and (provider := self.provider_resolver()) is not None:
            local_result = await self._verify_token_locally(provider, token)
            if local_result.status == "verified":
                return local_result.token
            if local_result.status == "rejected":
                return None

        remote_result = await self._verify_token_via_jwks(token)
        if remote_result.status == "verified":
            return remote_result.token
        if remote_result.status == "rejected":
            return None

        return await self._verify_token_via_introspection(token)

    async def _verify_token_locally(
        self,
        provider: SimpleOAuthProvider,
        token: str,
    ) -> _TokenVerification:
        verified_token = await verify_local_access_token(provider, token)
        if verified_token is None:
            return _TokenVerification(status="not_found")
        stored_token = verified_token.token

        if self.validate_resource and not self._validate_resource_value(stored_token.resource):
            logger.warning("Token resource validation failed. Expected: %s", self.resource_url)
            return _TokenVerification(status="rejected")

        return _TokenVerification(
            status="verified",
            token=AccessToken(
                token=token,
                client_id=stored_token.client_id,
                scopes=stored_token.scopes,
                expires_at=stored_token.expires_at,
                resource=_normalize_resource(stored_token.resource),
            ),
        )

    async def _verify_token_via_jwks(self, token: str) -> _TokenVerification:
        if self.jwt_issuer is None or self.jwks_endpoint is None or not _is_safe_remote_endpoint(self.jwks_endpoint):
            if self.jwks_endpoint is not None and not _is_safe_remote_endpoint(self.jwks_endpoint):
                logger.warning("Rejecting JWKS endpoint with unsafe scheme: %s", self.jwks_endpoint)
            return _TokenVerification(status="not_found")

        signing_key = await self._get_signing_key_from_jwt(token)
        if signing_key is None:
            return _TokenVerification(status="not_found")

        try:
            payload = jwt.decode(
                token,
                signing_key.key,
                algorithms=[self.jwt_algorithm],
                issuer=self.jwt_issuer,
                options={
                    "verify_aud": False,
                    # Belgie can legitimately issue resource-bound machine tokens without a string sub.
                    "verify_sub": False,
                },
            )
        except InvalidTokenError as exc:
            logger.debug("Remote JWT verification failed: %s", exc)
            return _TokenVerification(status="not_found")

        resource = _coerce_resource_claim(payload.get("aud"))
        if resource is None:
            return _TokenVerification(status="not_found")

        if self.validate_resource and not self._validate_resource_value(resource):
            logger.warning("Token resource validation failed. Expected: %s", self.resource_url)
            return _TokenVerification(status="rejected")

        return _TokenVerification(
            status="verified",
            token=AccessToken(
                token=token,
                client_id=_coerce_client_id(payload),
                scopes=_coerce_scope_claim(payload.get("scope")),
                expires_at=_coerce_exp_claim(payload.get("exp")),
                resource=_normalize_resource(resource),
            ),
        )

    async def _get_signing_key_from_jwt(self, token: str) -> jwt.PyJWK | None:
        try:
            header = jwt.get_unverified_header(token)
        except DecodeError:
            return None

        kid = header.get("kid")
        if not isinstance(kid, str) or not kid:
            return None

        jwks = await self._load_jwks()
        if jwks is None:
            return None

        signing_key = _get_jwk_for_kid(jwks, kid)
        if signing_key is not None:
            return signing_key

        refreshed_jwks = await self._load_jwks(refresh=True)
        if refreshed_jwks is None:
            return None

        return _get_jwk_for_kid(refreshed_jwks, kid)

    async def _load_jwks(self, *, refresh: bool = False) -> PyJWKSet | None:
        if self.jwks_endpoint is None:
            return None

        now = monotonic()
        if (
            not refresh
            and self._jwks is not None
            and self._jwks_fetched_at is not None
            and now - self._jwks_fetched_at < _JWKS_CACHE_TTL_SECONDS
        ):
            return self._jwks

        async with _build_http_client() as client:
            try:
                response = await client.get(
                    self.jwks_endpoint,
                    headers={"Accept": "application/json"},
                )
            except HTTPError as exc:
                logger.warning("JWKS fetch failed: %s", exc)
                return None

        if response.status_code != _HTTP_OK:
            logger.debug("JWKS fetch returned status %s", response.status_code)
            return None

        try:
            jwks = PyJWKSet.from_dict(response.json())
        except (PyJWKSetError, TypeError, ValueError) as exc:
            logger.warning("JWKS response could not be parsed: %s", exc)
            return None

        self._jwks = jwks
        self._jwks_fetched_at = now
        return jwks

    async def _verify_token_via_introspection(self, token: str) -> AccessToken | None:
        if not _is_safe_remote_endpoint(self.introspection_endpoint):
            logger.warning("Rejecting introspection endpoint with unsafe scheme: %s", self.introspection_endpoint)
            return None

        async with _build_http_client() as client:
            try:
                response = await client.post(
                    self.introspection_endpoint,
                    data={"token": token},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    auth=(
                        (self.introspection_client_id, self.introspection_client_secret)
                        if self.introspection_client_id is not None and self.introspection_client_secret is not None
                        else None
                    ),
                )
            except HTTPError as exc:
                logger.warning("Token introspection failed: %s", exc)
                return None

        if response.status_code != _HTTP_OK:
            logger.debug("Token introspection returned status %s", response.status_code)
            return None

        data = response.json()
        if not data.get("active", False):
            return None

        if self.validate_resource and not self._validate_resource(data):
            logger.warning("Token resource validation failed. Expected: %s", self.resource_url)
            return None

        scopes = data.get("scope", "")
        return AccessToken(
            token=token,
            client_id=data.get("client_id", "unknown"),
            scopes=scopes.split() if scopes else [],
            expires_at=data.get("exp"),
            resource=_normalize_resource(data.get("aud")),
        )

    def _validate_resource(self, token_data: dict[str, Any]) -> bool:
        if not self.server_url or not self.resource_url:
            return False

        return self._validate_resource_value(token_data.get("aud"))

    def _validate_resource_value(self, resource: list[str] | str | None) -> bool:
        if isinstance(resource, list):
            return any(self._is_valid_resource(audience) for audience in resource)
        if resource:
            return self._is_valid_resource(resource)
        return False

    def _is_valid_resource(self, resource: str) -> bool:
        return check_resource_allowed(requested_resource=self.resource_url, configured_resource=resource)


def mcp_auth(
    settings: OAuthServer,
    *,
    server_url: str | AnyHttpUrl,
    required_scopes: list[str] | None = None,
) -> AuthSettings:
    issuer_url = _require_issuer_url(settings)
    resource_server_url = AnyHttpUrl(str(server_url))
    scopes = required_scopes if required_scopes is not None else list(settings.default_scopes)

    return AuthSettings(
        issuer_url=AnyHttpUrl(issuer_url),
        resource_server_url=resource_server_url,
        required_scopes=scopes,
    )


def mcp_token_verifier(  # noqa: PLR0913
    settings: OAuthServer,
    *,
    server_url: str | AnyHttpUrl,
    introspection_endpoint: str | None = None,
    introspection_client_id: str | None = None,
    introspection_client_secret: str | None = None,
    oauth_strict: bool = False,
    provider_resolver: Callable[[], SimpleOAuthProvider | None] | None = None,
) -> TokenVerifier:
    issuer_url = _require_issuer_url(settings)
    endpoint = join_url(issuer_url, "introspect") if introspection_endpoint is None else introspection_endpoint
    jwks_endpoint = join_url(issuer_url, "jwks") if settings.signing.algorithm != "HS256" else None
    return BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url=str(server_url),
        provider_resolver=provider_resolver,
        validate_resource=oauth_strict,
        introspection_client_id=introspection_client_id,
        introspection_client_secret=introspection_client_secret,
        jwt_issuer=issuer_url,
        jwks_endpoint=jwks_endpoint,
        jwt_algorithm=settings.signing.algorithm,
    )


def _build_http_client() -> AsyncClient:
    return AsyncClient(
        timeout=Timeout(10.0, connect=5.0),
        limits=Limits(max_connections=10, max_keepalive_connections=5),
        verify=True,
    )


def _is_safe_remote_endpoint(endpoint: str) -> bool:
    return endpoint.startswith(("https://", "http://localhost", "http://127.0.0.1"))


def _require_issuer_url(settings: OAuthServer) -> str:
    if settings.issuer_url is None:
        msg = "OAuthServer.issuer_url is required to build MCP AuthSettings"
        raise ValueError(msg)
    return str(settings.issuer_url)


def _normalize_resource(resource: list[str] | str | None) -> str | None:
    if isinstance(resource, list):
        return None if not resource else resource[0]
    return resource


def _coerce_client_id(payload: dict[str, Any]) -> str:
    azp = payload.get("azp")
    if isinstance(azp, str) and azp:
        return azp
    client_id = payload.get("client_id")
    if isinstance(client_id, str) and client_id:
        return client_id
    return "unknown"


def _coerce_scope_claim(scope: object) -> list[str]:
    if not isinstance(scope, str) or not scope:
        return []
    return scope.split()


def _coerce_exp_claim(exp: object) -> int | None:
    if isinstance(exp, bool):
        return None
    if isinstance(exp, (int, float)):
        return int(exp)
    return None


def _coerce_resource_claim(resource: object) -> list[str] | str | None:
    if isinstance(resource, str):
        return resource
    if isinstance(resource, list) and all(isinstance(audience, str) for audience in resource):
        return resource
    return None


def _get_jwk_for_kid(jwks: PyJWKSet, kid: str) -> jwt.PyJWK | None:
    try:
        return jwks[kid]
    except KeyError:
        return None
