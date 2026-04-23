from __future__ import annotations

import httpx
import pytest
import respx
from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig
from belgie_sso.discovery import discover_oidc_configuration, needs_runtime_discovery, normalize_oidc_metadata


@pytest.mark.asyncio
async def test_discover_oidc_configuration_normalizes_relative_endpoints() -> None:
    issuer = "https://idp.example.com/tenant"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    with respx.mock(assert_all_called=True) as router:
        router.get(discovery_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": "/oauth2/authorize",
                    "token_endpoint": "oauth2/token",
                    "userinfo_endpoint": "userinfo",
                    "jwks_uri": "/jwks",
                },
            ),
        )

        discovery = await discover_oidc_configuration(
            issuer=issuer,
            client_id="client-id",
            client_secret="client-secret",
            scopes=["openid", "email", "profile"],
            token_endpoint_auth_method="client_secret_basic",
            claim_mapping=OIDCClaimMapping(),
            timeout_seconds=5,
        )

    assert discovery.config.authorization_endpoint == "https://idp.example.com/oauth2/authorize"
    assert discovery.config.token_endpoint == "https://idp.example.com/tenant/oauth2/token"  # noqa: S105
    assert discovery.config.userinfo_endpoint == "https://idp.example.com/tenant/userinfo"
    assert discovery.config.jwks_uri == "https://idp.example.com/jwks"


@pytest.mark.asyncio
async def test_discover_oidc_configuration_rejects_untrusted_endpoint_origin() -> None:
    issuer = "https://idp.example.com"
    discovery_url = f"{issuer}/.well-known/openid-configuration"
    with respx.mock(assert_all_called=True) as router:
        router.get(discovery_url).mock(
            return_value=httpx.Response(
                200,
                json={
                    "issuer": issuer,
                    "authorization_endpoint": "https://evil.example.com/authorize",
                    "token_endpoint": "https://idp.example.com/token",
                    "jwks_uri": "https://idp.example.com/jwks",
                },
            ),
        )

        with pytest.raises(ValueError, match="allowed origin"):
            await discover_oidc_configuration(
                issuer=issuer,
                client_id="client-id",
                client_secret="client-secret",
                scopes=["openid", "email", "profile"],
                token_endpoint_auth_method="client_secret_basic",
                claim_mapping=OIDCClaimMapping(),
                timeout_seconds=5,
            )


def test_normalize_oidc_metadata_rejects_issuer_mismatch() -> None:
    with pytest.raises(ValueError, match="issuer does not match"):
        normalize_oidc_metadata(
            metadata={
                "issuer": "https://different.example.com",
                "authorization_endpoint": "https://idp.example.com/authorize",
                "token_endpoint": "https://idp.example.com/token",
                "jwks_uri": "https://idp.example.com/jwks",
            },
            issuer="https://idp.example.com",
        )


def test_normalize_oidc_metadata_requires_jwks_uri() -> None:
    with pytest.raises(ValueError, match="jwks_uri"):
        normalize_oidc_metadata(
            metadata={
                "issuer": "https://idp.example.com",
                "authorization_endpoint": "https://idp.example.com/authorize",
                "token_endpoint": "https://idp.example.com/token",
            },
            issuer="https://idp.example.com",
        )


def test_needs_runtime_discovery_requires_jwks_uri() -> None:
    assert needs_runtime_discovery(
        OIDCProviderConfig(
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
            authorization_endpoint="https://idp.example.com/authorize",
            token_endpoint="https://idp.example.com/token",
            jwks_uri=None,
        ),
    )
