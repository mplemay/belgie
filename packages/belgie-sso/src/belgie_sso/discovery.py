from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

import httpx
from belgie_oauth._transport import OAuthTransport
from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig

from belgie_sso.utils import _normalize_origin, normalize_issuer, resolve_http_url

if TYPE_CHECKING:
    from collections.abc import Mapping

    from belgie_oauth._types import ProviderMetadata


@dataclass(slots=True, kw_only=True, frozen=True)
class OIDCDiscoveryResult:
    issuer: str
    config: OIDCProviderConfig


def _coerce_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def normalize_oidc_metadata(
    *,
    metadata: Mapping[str, object],
    issuer: str,
    discovery_endpoint: str | None = None,
    trusted_origins: tuple[str, ...] = (),
) -> dict[str, str | None]:
    normalized_issuer = normalize_issuer(issuer)
    if normalize_issuer(_coerce_optional_string(metadata.get("issuer")) or normalized_issuer) != normalized_issuer:
        msg = "discovery issuer does not match requested issuer"
        raise ValueError(msg)

    allowed_origins = {
        _normalize_origin(normalized_issuer),
        *(_normalize_origin(origin) for origin in trusted_origins),
    }
    if discovery_endpoint is not None:
        allowed_origins.add(_normalize_origin(discovery_endpoint))

    normalized: dict[str, str | None] = {"issuer": normalized_issuer}
    for key in ("authorization_endpoint", "token_endpoint", "userinfo_endpoint", "jwks_uri"):
        raw_value = _coerce_optional_string(metadata.get(key))
        if raw_value is None:
            if key in {"authorization_endpoint", "token_endpoint", "jwks_uri"}:
                msg = f"missing required discovery field: {key}"
                raise ValueError(msg)
            normalized[key] = None
            continue
        resolved = resolve_http_url(raw_value, base_url=normalized_issuer, field_name=key)
        if _normalize_origin(resolved) not in allowed_origins:
            msg = f"discovered endpoint '{key}' is not on an allowed origin"
            raise ValueError(msg)
        normalized[key] = resolved
    return normalized


def needs_runtime_discovery(config: OIDCProviderConfig) -> bool:
    return config.authorization_endpoint is None or config.token_endpoint is None or config.jwks_uri is None


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
    trusted_origins: tuple[str, ...] = (),
    use_pkce: bool = True,
    override_user_info_on_sign_in: bool = False,
) -> OIDCDiscoveryResult:
    normalized_issuer = normalize_issuer(issuer)
    discovery_url = discovery_endpoint or f"{normalized_issuer}/.well-known/openid-configuration"

    async with httpx.AsyncClient(timeout=timeout_seconds) as http_client:
        response = await http_client.get(discovery_url)
        response.raise_for_status()
        document = response.json()

    normalized_metadata = normalize_oidc_metadata(
        metadata=document,
        issuer=normalized_issuer,
        discovery_endpoint=discovery_url,
        trusted_origins=trusted_origins,
    )
    raw_supported_methods = document.get("token_endpoint_auth_methods_supported")
    supported_methods = (
        [item for item in raw_supported_methods if isinstance(item, str)]
        if isinstance(raw_supported_methods, list)
        else ["client_secret_basic"]
    )
    if token_endpoint_auth_method not in supported_methods:
        msg = f"token endpoint auth method '{token_endpoint_auth_method}' is not supported"
        raise ValueError(msg)

    return OIDCDiscoveryResult(
        issuer=normalized_issuer,
        config=OIDCProviderConfig(
            issuer=normalized_issuer,
            client_id=client_id,
            client_secret=client_secret,
            authorization_endpoint=normalized_metadata["authorization_endpoint"],
            token_endpoint=normalized_metadata["token_endpoint"],
            userinfo_endpoint=normalized_metadata["userinfo_endpoint"],
            discovery_endpoint=discovery_url,
            jwks_uri=normalized_metadata["jwks_uri"],
            scopes=tuple(scopes),
            token_endpoint_auth_method=token_endpoint_auth_method,
            use_pkce=use_pkce,
            override_user_info_on_sign_in=override_user_info_on_sign_in,
            claim_mapping=claim_mapping,
        ),
    )


class ValidatingOAuthTransport(OAuthTransport):
    def __init__(
        self,
        *args: object,
        issuer: str,
        discovery_endpoint: str | None,
        trusted_origins: tuple[str, ...],
        **kwargs: object,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._issuer = issuer
        self._discovery_endpoint = discovery_endpoint
        self._trusted_origins = trusted_origins

    async def resolve_server_metadata(self) -> ProviderMetadata:
        metadata = await super().resolve_server_metadata()
        normalized = normalize_oidc_metadata(
            metadata=metadata,
            issuer=self._issuer,
            discovery_endpoint=self._discovery_endpoint,
            trusted_origins=self._trusted_origins,
        )
        resolved = dict(metadata)
        resolved.update(normalized)
        return resolved
