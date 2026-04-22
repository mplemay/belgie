from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

import httpx
from authlib.oauth2.rfc6750.errors import InsufficientScopeError, InvalidTokenError
from authlib.oauth2.rfc7662 import IntrospectTokenValidator
from authlib.oauth2.rfc9068.claims import JWTAccessTokenClaims
from authlib.oauth2.rfc9068.token_validator import JWTBearerTokenValidator
from joserfc import jwt
from joserfc.errors import DecodeError, JoseError
from joserfc.jwk import OctKey, RSAKey
from pydantic import ValidationError

from belgie_oauth_server.models import OAuthServerIntrospectionResponse
from belgie_oauth_server.provider import AccessToken, SimpleOAuthProvider
from belgie_oauth_server.verifier import verify_local_access_token

_HTTP_OK = 200

type ResourceValidator = Callable[[list[str] | str | None], bool]


@dataclass(frozen=True, slots=True, kw_only=True)
class RemoteIntrospectionConfig:
    introspection_endpoint: str
    client_id: str | None = None
    client_secret: str | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class VerifiedResourceAccessToken:
    source: Literal["jwt", "stored", "introspection"]
    token: AccessToken
    subject: str | None = None
    issuer: str | None = None

    @property
    def individual_id(self) -> str | None:
        return self.token.individual_id


class _AuthlibIntrospectionPayloadValidator(IntrospectTokenValidator):
    def introspect_token(self, token_string: str) -> dict[str, object]:  # pragma: no cover
        msg = f"Direct introspection is not supported for {token_string!r}"
        raise NotImplementedError(msg)


class _BelgieJWTBearerTokenValidator(JWTBearerTokenValidator):
    def __init__(
        self,
        provider: SimpleOAuthProvider,
        *,
        resource_server: list[str] | str | None = None,
    ) -> None:
        super().__init__(issuer=provider.issuer_url, resource_server=resource_server)
        self.provider = provider

    def get_jwks(self) -> str | bytes:
        # Keep Belgie's signing configuration as the source of truth while
        # delegating JWT claim validation to Authlib's RFC 9068 machinery.
        return self.provider.signing_state.verification_key

    def authenticate_token(self, token_string: str) -> JWTAccessTokenClaims:
        claims_options = {
            "iss": {"essential": True, "validate": self.validate_iss},
            "exp": {"essential": True},
            "iat": {"essential": True},
            "azp": {"essential": True},
            "scope": {"essential": False},
            "groups": {"essential": False},
            "roles": {"essential": False},
            "entitlements": {"essential": False},
        }
        if self.resource_server is not None:
            claims_options["aud"] = {
                "essential": True,
                **(
                    {"values": self.resource_server}
                    if isinstance(self.resource_server, list)
                    else {"value": self.resource_server}
                ),
            }

        key = _import_verification_key(self.provider)
        try:
            token = jwt.decode(token_string, key=key)
            header = dict(token.header)
            if header.get("typ", "").lower() == "jwt":
                header["typ"] = "at+jwt"
            return JWTAccessTokenClaims(token.claims, header, claims_options)
        except DecodeError as exc:
            raise InvalidTokenError(
                realm=self.realm,
                extra_attributes=self.extra_attributes,
            ) from exc


async def verify_resource_access_token(  # noqa: PLR0911
    token: str,
    *,
    provider: SimpleOAuthProvider | None = None,
    resource_validator: ResourceValidator | None = None,
    introspection: RemoteIntrospectionConfig | None = None,
    verify_exp: bool = True,
) -> VerifiedResourceAccessToken | None:
    if provider is not None:
        local_token = await verify_local_access_token(
            provider,
            token,
            verify_exp=verify_exp,
        )
        if local_token is not None:
            if (
                local_token.source == "jwt"
                and verify_exp
                and not _local_jwt_is_authlib_valid(
                    provider,
                    token,
                    resource=local_token.token.resource,
                )
            ):
                return None
            verified_token = await _build_local_verified_token(provider, local_token.source, local_token.token)
            if not _resource_allowed(verified_token.token.resource, resource_validator):
                return None
            return verified_token

    if introspection is None:
        return None

    payload = await _introspect_access_token(introspection, token)
    if payload is None or not _introspection_payload_is_valid(payload):
        return None

    verified_token = VerifiedResourceAccessToken(
        source="introspection",
        token=AccessToken(
            token=token,
            client_id=payload.client_id or "unknown",
            scopes=payload.scope.split() if payload.scope else [],
            created_at=payload.iat if payload.iat is not None else int(time.time()),
            expires_at=payload.exp,
            resource=payload.aud,
            individual_id=None,
            session_id=payload.sid,
        ),
        subject=payload.sub,
        issuer=payload.iss,
    )
    if not _resource_allowed(verified_token.token.resource, resource_validator):
        return None
    return verified_token


async def _build_local_verified_token(
    provider: SimpleOAuthProvider,
    source: Literal["jwt", "stored"],
    token: AccessToken,
) -> VerifiedResourceAccessToken:
    subject = token.individual_id
    if token.individual_id is not None:
        oauth_client = await provider.get_client(token.client_id)
        if oauth_client is not None:
            subject = provider.resolve_subject_identifier(oauth_client, token.individual_id)
    return VerifiedResourceAccessToken(
        source=source,
        token=token,
        subject=subject,
        issuer=provider.issuer_url,
    )


async def _introspect_access_token(
    config: RemoteIntrospectionConfig,
    token: str,
) -> OAuthServerIntrospectionResponse | None:
    if not _is_safe_introspection_endpoint(config.introspection_endpoint):
        return None

    timeout = httpx.Timeout(10.0, connect=5.0)
    limits = httpx.Limits(max_connections=10, max_keepalive_connections=5)
    async with httpx.AsyncClient(timeout=timeout, limits=limits, verify=True) as client:
        response = await client.post(
            config.introspection_endpoint,
            data={"token": token},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            auth=(
                (config.client_id, config.client_secret)
                if config.client_id is not None and config.client_secret is not None
                else None
            ),
        )

    if response.status_code != _HTTP_OK:
        return None

    try:
        return OAuthServerIntrospectionResponse.model_validate(response.json())
    except (ValidationError, ValueError):
        return None


def _introspection_payload_is_valid(payload: OAuthServerIntrospectionResponse) -> bool:
    validator = _AuthlibIntrospectionPayloadValidator()
    try:
        validator.validate_token(payload.model_dump(mode="python"), scopes=[], request=None)
    except (InsufficientScopeError, InvalidTokenError):
        return False
    return True


def _local_jwt_is_authlib_valid(
    provider: SimpleOAuthProvider,
    token: str,
    *,
    resource: list[str] | str | None,
) -> bool:
    validator = _BelgieJWTBearerTokenValidator(provider, resource_server=resource)
    try:
        claims = validator.authenticate_token(token)
        validator.validate_token(claims, scopes=[], request=None)
    except (InvalidTokenError, JoseError):
        return False
    return True


def _import_verification_key(provider: SimpleOAuthProvider) -> OctKey | RSAKey:
    key = provider.signing_state.verification_key
    if provider.signing_state.algorithm == "HS256":
        return OctKey.import_key(key)
    return RSAKey.import_key(key)


def _resource_allowed(
    resource: list[str] | str | None,
    validator: ResourceValidator | None,
) -> bool:
    if validator is None:
        return True
    return validator(resource)


def _is_safe_introspection_endpoint(endpoint: str) -> bool:
    return endpoint.startswith(("https://", "http://localhost", "http://127.0.0.1"))
