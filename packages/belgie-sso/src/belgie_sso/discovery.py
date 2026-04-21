from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse, urlunparse

import httpx
from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig
from pydantic import BaseModel, ConfigDict

from belgie_sso.utils import normalize_issuer


class DiscoveryDocument(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    issuer: str
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    userinfo_endpoint: str | None = None
    jwks_uri: str | None = None
    token_endpoint_auth_methods_supported: list[str] | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class OIDCDiscoveryResult:
    issuer: str
    config: OIDCProviderConfig


def normalize_absolute_url(url: str) -> str:
    value = url.strip()
    parsed = urlparse(value)
    if not parsed.scheme or not parsed.netloc:
        msg = "discovery endpoint must be an absolute URL"
        raise ValueError(msg)
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path.rstrip("/"), "", "", ""))


def compute_discovery_url(*, issuer: str, discovery_endpoint: str | None = None) -> str:
    if discovery_endpoint:
        return normalize_absolute_url(discovery_endpoint)
    return f"{normalize_issuer(issuer)}/.well-known/openid-configuration"


def _validate_supported_auth_method(
    *,
    token_endpoint_auth_method: str,
    supported_methods: list[str] | None,
) -> None:
    supported = supported_methods or ["client_secret_basic"]
    if token_endpoint_auth_method not in supported:
        msg = f"token endpoint auth method '{token_endpoint_auth_method}' is not supported"
        raise ValueError(msg)


def _merge_discovery_document(
    *,
    base_config: OIDCProviderConfig,
    document: DiscoveryDocument,
    discovery_endpoint: str,
) -> OIDCProviderConfig:
    return OIDCProviderConfig(
        client_id=base_config.client_id,
        client_secret=base_config.client_secret,
        authorization_endpoint=base_config.authorization_endpoint or document.authorization_endpoint,
        token_endpoint=base_config.token_endpoint or document.token_endpoint,
        userinfo_endpoint=base_config.userinfo_endpoint or document.userinfo_endpoint,
        jwks_uri=base_config.jwks_uri or document.jwks_uri,
        discovery_endpoint=discovery_endpoint,
        scopes=base_config.scopes,
        token_endpoint_auth_method=base_config.token_endpoint_auth_method,
        claim_mapping=base_config.claim_mapping,
        pkce=base_config.pkce,
        override_user_info=base_config.override_user_info,
    )


def _validate_runtime_config(config: OIDCProviderConfig) -> None:
    if not config.authorization_endpoint:
        msg = "OIDC configuration is missing authorization_endpoint"
        raise ValueError(msg)
    if not config.token_endpoint:
        msg = "OIDC configuration is missing token_endpoint"
        raise ValueError(msg)
    if not config.userinfo_endpoint and not config.jwks_uri:
        msg = "OIDC configuration requires userinfo_endpoint or jwks_uri"
        raise ValueError(msg)


async def fetch_discovery_document(
    *,
    issuer: str,
    discovery_endpoint: str | None,
    timeout_seconds: float,
) -> tuple[str, DiscoveryDocument]:
    normalized_issuer = normalize_issuer(issuer)
    resolved_discovery_endpoint = compute_discovery_url(
        issuer=normalized_issuer,
        discovery_endpoint=discovery_endpoint,
    )
    async with httpx.AsyncClient(timeout=timeout_seconds) as http_client:
        response = await http_client.get(resolved_discovery_endpoint)
        response.raise_for_status()
        document = DiscoveryDocument.model_validate(response.json())

    if normalize_issuer(document.issuer) != normalized_issuer:
        msg = "discovery issuer does not match requested issuer"
        raise ValueError(msg)

    return resolved_discovery_endpoint, document


async def discover_oidc_configuration(  # noqa: PLR0913
    *,
    issuer: str,
    client_id: str,
    client_secret: str,
    scopes: list[str],
    token_endpoint_auth_method: str,
    claim_mapping: OIDCClaimMapping,
    timeout_seconds: float,
    discovery_endpoint: str | None = None,
    authorization_endpoint: str | None = None,
    token_endpoint: str | None = None,
    userinfo_endpoint: str | None = None,
    jwks_uri: str | None = None,
    pkce: bool = True,
    override_user_info: bool = False,
) -> OIDCDiscoveryResult:
    normalized_issuer = normalize_issuer(issuer)
    resolved_discovery_endpoint, document = await fetch_discovery_document(
        issuer=normalized_issuer,
        discovery_endpoint=discovery_endpoint,
        timeout_seconds=timeout_seconds,
    )
    _validate_supported_auth_method(
        token_endpoint_auth_method=token_endpoint_auth_method,
        supported_methods=document.token_endpoint_auth_methods_supported,
    )

    config = _merge_discovery_document(
        base_config=OIDCProviderConfig(
            client_id=client_id,
            client_secret=client_secret,
            authorization_endpoint=authorization_endpoint,
            token_endpoint=token_endpoint,
            userinfo_endpoint=userinfo_endpoint,
            jwks_uri=jwks_uri,
            discovery_endpoint=resolved_discovery_endpoint,
            scopes=tuple(scopes),
            token_endpoint_auth_method=token_endpoint_auth_method,
            claim_mapping=claim_mapping,
            pkce=pkce,
            override_user_info=override_user_info,
        ),
        document=document,
        discovery_endpoint=resolved_discovery_endpoint,
    )
    _validate_runtime_config(config)

    return OIDCDiscoveryResult(
        issuer=normalized_issuer,
        config=config,
    )


def needs_runtime_discovery(
    config: OIDCProviderConfig,
    *,
    require_userinfo_or_jwks: bool = True,
) -> bool:
    if not config.authorization_endpoint or not config.token_endpoint:
        return True
    return require_userinfo_or_jwks and not config.userinfo_endpoint and not config.jwks_uri


async def ensure_runtime_discovery(
    *,
    config: OIDCProviderConfig,
    issuer: str,
    timeout_seconds: float,
    require_userinfo_or_jwks: bool = True,
) -> OIDCProviderConfig:
    if not needs_runtime_discovery(
        config,
        require_userinfo_or_jwks=require_userinfo_or_jwks,
    ):
        return config

    resolved_discovery_endpoint, document = await fetch_discovery_document(
        issuer=issuer,
        discovery_endpoint=config.discovery_endpoint,
        timeout_seconds=timeout_seconds,
    )
    _validate_supported_auth_method(
        token_endpoint_auth_method=config.token_endpoint_auth_method,
        supported_methods=document.token_endpoint_auth_methods_supported,
    )
    hydrated = _merge_discovery_document(
        base_config=config,
        document=document,
        discovery_endpoint=resolved_discovery_endpoint,
    )
    _validate_runtime_config(hydrated)
    return hydrated
