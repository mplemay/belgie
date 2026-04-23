from __future__ import annotations

from dataclasses import dataclass

import httpx
from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig
from pydantic import BaseModel, ConfigDict

from belgie_sso.utils import normalize_issuer


class DiscoveryDocument(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    userinfo_endpoint: str | None = None
    jwks_uri: str | None = None
    token_endpoint_auth_methods_supported: list[str] | None = None


@dataclass(slots=True, kw_only=True, frozen=True)
class OIDCDiscoveryResult:
    issuer: str
    config: OIDCProviderConfig


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
    use_pkce: bool = True,
    override_user_info_on_sign_in: bool = False,
) -> OIDCDiscoveryResult:
    normalized_issuer = normalize_issuer(issuer)
    discovery_url = discovery_endpoint or f"{normalized_issuer}/.well-known/openid-configuration"

    async with httpx.AsyncClient(timeout=timeout_seconds) as http_client:
        response = await http_client.get(discovery_url)
        response.raise_for_status()
        document = DiscoveryDocument.model_validate(response.json())

    if normalize_issuer(document.issuer) != normalized_issuer:
        msg = "discovery issuer does not match requested issuer"
        raise ValueError(msg)

    supported_methods = document.token_endpoint_auth_methods_supported or ["client_secret_basic"]
    if token_endpoint_auth_method not in supported_methods:
        msg = f"token endpoint auth method '{token_endpoint_auth_method}' is not supported"
        raise ValueError(msg)

    return OIDCDiscoveryResult(
        issuer=normalized_issuer,
        config=OIDCProviderConfig(
            issuer=normalized_issuer,
            client_id=client_id,
            client_secret=client_secret,
            authorization_endpoint=document.authorization_endpoint,
            token_endpoint=document.token_endpoint,
            userinfo_endpoint=document.userinfo_endpoint,
            discovery_endpoint=discovery_url,
            jwks_uri=document.jwks_uri,
            scopes=tuple(scopes),
            token_endpoint_auth_method=token_endpoint_auth_method,
            use_pkce=use_pkce,
            override_user_info_on_sign_in=override_user_info_on_sign_in,
            claim_mapping=claim_mapping,
        ),
    )
