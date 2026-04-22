from __future__ import annotations

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_oauth import GoogleOAuth, GoogleOAuthPlugin, GoogleUserInfo
from belgie_oauth.google import _map_google_profile
from pydantic import SecretStr, ValidationError


def _build_plugin(settings: GoogleOAuth | None = None) -> GoogleOAuthPlugin:
    provider_settings = settings or GoogleOAuth(
        client_id="google-client-id",
        client_secret="google-client-secret",
    )
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000/app")
    return GoogleOAuthPlugin(belgie_settings, provider_settings)


def test_google_settings_defaults() -> None:
    settings = GoogleOAuth(
        client_id="google-client-id",
        client_secret="google-client-secret",
    )

    assert settings.scopes == ["openid", "email", "profile"]
    assert settings.access_type == "offline"
    assert settings.prompt == "consent"
    assert settings.allow_sign_up is True
    assert settings.require_explicit_sign_up is False


def test_google_settings_reject_empty_client_secret() -> None:
    with pytest.raises(ValidationError):
        GoogleOAuth(
            client_id="google-client-id",
            client_secret="",
        )


def test_google_plugin_redirect_uri_includes_base_path() -> None:
    plugin = _build_plugin()

    assert plugin.redirect_uri == "http://localhost:8000/app/auth/provider/google/callback"


def test_google_preset_uses_discovery_and_offline_defaults() -> None:
    settings = GoogleOAuth(
        client_id="google-client-id",
        client_secret="google-client-secret",
        token_encryption_secret=SecretStr("token-secret"),
        encrypt_tokens=True,
    )
    provider = settings.to_provider()

    assert provider.provider_id == "google"
    assert provider.discovery_url == "https://accounts.google.com/.well-known/openid-configuration"
    assert provider.access_type == "offline"
    assert provider.prompt == "consent"
    assert provider.encrypt_tokens is True


@pytest.mark.asyncio
async def test_google_authorization_url_includes_prompt_and_access_type() -> None:
    plugin = _build_plugin()
    plugin.resolve_server_metadata = AsyncMock(  # type: ignore[attr-defined]
        return_value={"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth"},
    )

    url = await plugin.generate_authorization_url("test-state", code_verifier="verifier", nonce="nonce")
    query = parse_qs(urlparse(url).query)

    assert query["prompt"][0] == "consent"
    assert query["access_type"][0] == "offline"
    assert query["scope"][0] == "openid email profile"


def test_google_profile_mapper_uses_oidc_fields() -> None:
    mapped = _map_google_profile(
        {
            "sub": "google-user-1",
            "email": "person@example.com",
            "email_verified": True,
            "name": "Test Person",
            "picture": "https://example.com/photo.jpg",
        },
        token_set=None,  # type: ignore[arg-type]
    )

    assert mapped.provider_account_id == "google-user-1"
    assert mapped.email == "person@example.com"
    assert mapped.email_verified is True


def test_google_userinfo_model_accepts_standard_oidc_fields() -> None:
    profile = GoogleUserInfo(
        sub="google-user-1",
        email="person@example.com",
        email_verified=True,
        name="Test Person",
    )

    assert profile.sub == "google-user-1"
    assert profile.email == "person@example.com"
