from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_oauth import MicrosoftOAuth, MicrosoftOAuthPlugin, MicrosoftUserInfo
from belgie_oauth.microsoft import _map_microsoft_profile
from pydantic import ValidationError


def _build_plugin(settings: MicrosoftOAuth | None = None) -> MicrosoftOAuthPlugin:
    provider_settings = settings or MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret="microsoft-client-secret",
    )
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    return MicrosoftOAuthPlugin(belgie_settings, provider_settings)


def test_microsoft_settings_defaults() -> None:
    settings = MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret="microsoft-client-secret",
    )

    assert settings.tenant == "common"
    assert settings.scopes == ["openid", "profile", "email", "offline_access", "User.Read"]


def test_microsoft_settings_reject_empty_tenant() -> None:
    with pytest.raises(ValidationError):
        MicrosoftOAuth(
            client_id="microsoft-client-id",
            client_secret="microsoft-client-secret",
            tenant="",
        )


def test_microsoft_common_tenant_preset_uses_graph_userinfo() -> None:
    settings = MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret="microsoft-client-secret",
    )
    provider = settings.to_provider()

    assert provider.authorization_endpoint == "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    assert provider.token_endpoint == "https://login.microsoftonline.com/common/oauth2/v2.0/token"  # noqa: S105
    assert provider.userinfo_endpoint == "https://graph.microsoft.com/oidc/userinfo"
    assert provider.issuer is None


def test_microsoft_public_client_mode_uses_none_auth() -> None:
    settings = MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret=None,
    )
    provider = settings.to_provider()

    assert provider.client_secret is None
    assert provider.token_endpoint_auth_method == "none"


def test_microsoft_tenant_specific_preset_sets_expected_issuer() -> None:
    settings = MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret="microsoft-client-secret",
        tenant="tenant-123",
    )
    provider = settings.to_provider()

    assert provider.issuer == "https://login.microsoftonline.com/tenant-123/v2.0"
    assert provider.jwks_uri == "https://login.microsoftonline.com/tenant-123/discovery/v2.0/keys"


@pytest.mark.asyncio
async def test_microsoft_authorization_url_includes_query_response_mode() -> None:
    plugin = _build_plugin()

    url = await plugin.generate_authorization_url("test-state", code_verifier="verifier", nonce="nonce")
    query = parse_qs(urlparse(url).query)

    assert query["response_mode"][0] == "query"
    assert query["scope"][0] == "openid profile email offline_access User.Read"


def test_microsoft_profile_mapper_falls_back_to_preferred_username() -> None:
    mapped = _map_microsoft_profile(
        {
            "sub": "microsoft-user-1",
            "preferred_username": "person@example.com",
            "name": "Microsoft Person",
        },
        token_set=None,  # type: ignore[arg-type]
    )

    assert mapped.provider_account_id == "microsoft-user-1"
    assert mapped.email == "person@example.com"
    assert mapped.email_verified is False


def test_microsoft_userinfo_model_resolves_email() -> None:
    profile = MicrosoftUserInfo(
        sub="microsoft-user-1",
        preferred_username="person@example.com",
    )

    assert profile.resolved_email == "person@example.com"
