from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest
import respx
from belgie_proto.sso import OIDCClaimMapping, OIDCProviderConfig
from belgie_sso.discovery import (
    DiscoveryError,
    OIDCDiscoveryResult,
    compute_discovery_url,
    discover_oidc_configuration,
    ensure_runtime_discovery,
    fetch_discovery_document,
    needs_runtime_discovery,
    normalize_oidc_metadata,
    validate_discovery_document,
    validate_discovery_url,
)


def _discovery_document(
    *,
    issuer: str = "https://idp.example.com",
    authorization_endpoint: str = "https://idp.example.com/authorize",
    token_endpoint: str | None = None,
    jwks_uri: str = "https://idp.example.com/jwks",
    userinfo_endpoint: str | None = "https://idp.example.com/userinfo",
    token_endpoint_auth_methods_supported: list[str] | None = None,
) -> dict[str, object]:
    document: dict[str, object] = {
        "issuer": issuer,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint or "https://idp.example.com/token",
        "jwks_uri": jwks_uri,
    }
    if userinfo_endpoint is not None:
        document["userinfo_endpoint"] = userinfo_endpoint
    if token_endpoint_auth_methods_supported is not None:
        document["token_endpoint_auth_methods_supported"] = token_endpoint_auth_methods_supported
    return document


def test_compute_discovery_url_appends_well_known_path() -> None:
    assert compute_discovery_url("https://idp.example.com/tenant/") == (
        "https://idp.example.com/tenant/.well-known/openid-configuration"
    )


def test_validate_discovery_url_rejects_invalid_protocol() -> None:
    with pytest.raises(DiscoveryError) as exc_info:
        validate_discovery_url(
            discovery_url="ftp://idp.example.com/openid-configuration",
            issuer="https://idp.example.com",
        )

    assert exc_info.value.code == "discovery_invalid_url"


def test_validate_discovery_url_rejects_untrusted_origin() -> None:
    with pytest.raises(DiscoveryError) as exc_info:
        validate_discovery_url(
            discovery_url="https://metadata.example.com/openid-configuration",
            issuer="https://idp.example.com",
        )

    assert exc_info.value.code == "discovery_untrusted_origin"


@pytest.mark.asyncio
async def test_fetch_discovery_document_raises_not_found_for_404() -> None:
    discovery_url = compute_discovery_url("https://idp.example.com")
    with respx.mock(assert_all_called=True) as router:
        router.get(discovery_url).mock(return_value=httpx.Response(404))

        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_discovery_document(discovery_url=discovery_url, timeout_seconds=5)

    assert exc_info.value.code == "discovery_not_found"


@pytest.mark.asyncio
async def test_fetch_discovery_document_raises_timeout_for_network_timeout() -> None:
    discovery_url = compute_discovery_url("https://idp.example.com")
    with respx.mock(assert_all_called=True) as router:
        router.get(discovery_url).mock(side_effect=httpx.ReadTimeout("timed out"))

        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_discovery_document(discovery_url=discovery_url, timeout_seconds=5)

    assert exc_info.value.code == "discovery_timeout"


@pytest.mark.asyncio
async def test_fetch_discovery_document_raises_invalid_json_for_non_json_response() -> None:
    discovery_url = compute_discovery_url("https://idp.example.com")
    with respx.mock(assert_all_called=True) as router:
        router.get(discovery_url).mock(return_value=httpx.Response(200, text="not-json"))

        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_discovery_document(discovery_url=discovery_url, timeout_seconds=5)

    assert exc_info.value.code == "discovery_invalid_json"


@pytest.mark.asyncio
async def test_fetch_discovery_document_raises_unexpected_error_for_server_error() -> None:
    discovery_url = compute_discovery_url("https://idp.example.com")
    with respx.mock(assert_all_called=True) as router:
        router.get(discovery_url).mock(return_value=httpx.Response(500))

        with pytest.raises(DiscoveryError) as exc_info:
            await fetch_discovery_document(discovery_url=discovery_url, timeout_seconds=5)

    assert exc_info.value.code == "discovery_unexpected_error"


@pytest.mark.asyncio
async def test_discover_oidc_configuration_normalizes_relative_endpoints() -> None:
    issuer = "https://idp.example.com/tenant"
    discovery_url = compute_discovery_url(issuer)
    with respx.mock(assert_all_called=True) as router:
        router.get(discovery_url).mock(
            return_value=httpx.Response(
                200,
                json=_discovery_document(
                    issuer=issuer,
                    authorization_endpoint="/oauth2/authorize",
                    token_endpoint="oauth2/token",
                    userinfo_endpoint="userinfo",
                    jwks_uri="/jwks",
                ),
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
async def test_discover_oidc_configuration_uses_custom_discovery_endpoint() -> None:
    issuer = "https://idp.example.com"
    custom_discovery_url = "https://metadata.example.com/openid-configuration"
    with respx.mock(assert_all_called=True) as router:
        router.get(custom_discovery_url).mock(return_value=httpx.Response(200, json=_discovery_document(issuer=issuer)))

        discovery = await discover_oidc_configuration(
            issuer=issuer,
            client_id="client-id",
            client_secret="client-secret",
            scopes=["openid", "email", "profile"],
            token_endpoint_auth_method="client_secret_basic",
            claim_mapping=OIDCClaimMapping(),
            timeout_seconds=5,
            discovery_endpoint=custom_discovery_url,
            trusted_origins=("https://metadata.example.com",),
        )

    assert discovery.config.discovery_endpoint == custom_discovery_url


@pytest.mark.asyncio
async def test_discover_oidc_configuration_rejects_untrusted_main_discovery_url() -> None:
    with pytest.raises(DiscoveryError) as exc_info:
        await discover_oidc_configuration(
            issuer="https://idp.example.com",
            client_id="client-id",
            client_secret="client-secret",
            scopes=["openid", "email", "profile"],
            token_endpoint_auth_method="client_secret_basic",
            claim_mapping=OIDCClaimMapping(),
            timeout_seconds=5,
            discovery_endpoint="https://metadata.example.com/openid-configuration",
        )

    assert exc_info.value.code == "discovery_untrusted_origin"


@pytest.mark.asyncio
async def test_discover_oidc_configuration_rejects_untrusted_endpoint_origin() -> None:
    issuer = "https://idp.example.com"
    discovery_url = compute_discovery_url(issuer)
    with respx.mock(assert_all_called=True) as router:
        router.get(discovery_url).mock(
            return_value=httpx.Response(
                200,
                json=_discovery_document(
                    issuer=issuer,
                    authorization_endpoint="https://evil.example.com/authorize",
                ),
            ),
        )

        with pytest.raises(DiscoveryError) as exc_info:
            await discover_oidc_configuration(
                issuer=issuer,
                client_id="client-id",
                client_secret="client-secret",
                scopes=["openid", "email", "profile"],
                token_endpoint_auth_method="client_secret_basic",
                claim_mapping=OIDCClaimMapping(),
                timeout_seconds=5,
            )

    assert exc_info.value.code == "discovery_untrusted_origin"


@pytest.mark.asyncio
async def test_discover_oidc_configuration_selects_supported_token_auth_method() -> None:
    issuer = "https://idp.example.com"
    discovery_url = compute_discovery_url(issuer)
    with respx.mock(assert_all_called=True) as router:
        router.get(discovery_url).mock(
            return_value=httpx.Response(
                200,
                json=_discovery_document(
                    issuer=issuer,
                    token_endpoint_auth_methods_supported=["client_secret_post"],
                ),
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

    assert discovery.config.token_endpoint_auth_method == "client_secret_post"  # noqa: S105


def test_validate_discovery_document_requires_required_fields() -> None:
    with pytest.raises(DiscoveryError) as exc_info:
        validate_discovery_document(
            metadata={
                "issuer": "https://idp.example.com",
                "authorization_endpoint": "https://idp.example.com/authorize",
                "token_endpoint": "https://idp.example.com/token",
            },
            issuer="https://idp.example.com",
        )

    assert exc_info.value.code == "discovery_incomplete"


def test_validate_discovery_document_rejects_issuer_mismatch() -> None:
    with pytest.raises(DiscoveryError) as exc_info:
        validate_discovery_document(
            metadata=_discovery_document(issuer="https://different.example.com"),
            issuer="https://idp.example.com",
        )

    assert exc_info.value.code == "issuer_mismatch"


def test_normalize_oidc_metadata_rejects_issuer_mismatch() -> None:
    with pytest.raises(DiscoveryError) as exc_info:
        normalize_oidc_metadata(
            metadata=_discovery_document(issuer="https://different.example.com"),
            issuer="https://idp.example.com",
        )

    assert exc_info.value.code == "issuer_mismatch"


def test_normalize_oidc_metadata_requires_jwks_uri() -> None:
    with pytest.raises(DiscoveryError) as exc_info:
        normalize_oidc_metadata(
            metadata={
                "issuer": "https://idp.example.com",
                "authorization_endpoint": "https://idp.example.com/authorize",
                "token_endpoint": "https://idp.example.com/token",
            },
            issuer="https://idp.example.com",
        )

    assert exc_info.value.code == "discovery_incomplete"


def test_normalize_oidc_metadata_rejects_invalid_protocol() -> None:
    with pytest.raises(DiscoveryError) as exc_info:
        normalize_oidc_metadata(
            metadata=_discovery_document(
                authorization_endpoint="ftp://idp.example.com/authorize",
            ),
            issuer="https://idp.example.com",
        )

    assert exc_info.value.code == "discovery_invalid_url"


@pytest.mark.asyncio
async def test_ensure_runtime_discovery_returns_existing_config_when_not_needed() -> None:
    config = OIDCProviderConfig(
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        authorization_endpoint="https://idp.example.com/authorize",
        token_endpoint="https://idp.example.com/token",
        userinfo_endpoint="https://idp.example.com/userinfo",
        discovery_endpoint=compute_discovery_url("https://idp.example.com"),
        jwks_uri="https://idp.example.com/jwks",
    )

    hydrated = await ensure_runtime_discovery(config=config, timeout_seconds=5)

    assert hydrated == config


@pytest.mark.asyncio
async def test_ensure_runtime_discovery_hydrates_missing_fields_without_overwriting_existing(monkeypatch) -> None:
    config = OIDCProviderConfig(
        issuer="https://idp.example.com",
        client_id="client-id",
        client_secret="client-secret",
        authorization_endpoint=None,
        token_endpoint=None,
        userinfo_endpoint="https://custom.example.com/userinfo",
        discovery_endpoint=compute_discovery_url("https://idp.example.com"),
        jwks_uri="https://custom.example.com/jwks",
    )
    monkeypatch.setattr(
        "belgie_sso.discovery.discover_oidc_configuration",
        AsyncMock(
            return_value=OIDCDiscoveryResult(
                issuer="https://idp.example.com",
                config=OIDCProviderConfig(
                    issuer="https://idp.example.com",
                    client_id="client-id",
                    client_secret="client-secret",
                    authorization_endpoint="https://idp.example.com/authorize",
                    token_endpoint="https://idp.example.com/token",
                    userinfo_endpoint="https://idp.example.com/userinfo",
                    discovery_endpoint=compute_discovery_url("https://idp.example.com"),
                    jwks_uri="https://idp.example.com/jwks",
                ),
            ),
        ),
    )

    hydrated = await ensure_runtime_discovery(config=config, timeout_seconds=5)

    assert hydrated.authorization_endpoint == "https://idp.example.com/authorize"
    assert hydrated.token_endpoint == "https://idp.example.com/token"  # noqa: S105
    assert hydrated.userinfo_endpoint == "https://custom.example.com/userinfo"
    assert hydrated.jwks_uri == "https://custom.example.com/jwks"


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
