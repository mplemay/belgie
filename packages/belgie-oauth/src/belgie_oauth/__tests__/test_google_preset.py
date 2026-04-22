from __future__ import annotations

from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from belgie_core.core.settings import BelgieSettings
from belgie_oauth import GoogleOAuth, GoogleOAuthPlugin, GoogleUserInfo, OAuthTokenSet
from belgie_oauth.__tests__.helpers import build_jwks_document, build_rsa_signing_key, issue_id_token
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
    assert settings.include_granted_scopes is True
    assert settings.disable_sign_up is False
    assert settings.disable_implicit_sign_up is False


def test_google_settings_reject_empty_client_secret() -> None:
    with pytest.raises(ValidationError):
        GoogleOAuth(
            client_id="google-client-id",
            client_secret="",
        )


def test_google_settings_reject_empty_client_id_list() -> None:
    with pytest.raises(ValidationError):
        GoogleOAuth(
            client_id=[],
            client_secret="google-client-secret",
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
    assert provider.authorization_params["include_granted_scopes"] == "true"
    assert provider.encrypt_tokens is True


def test_google_preset_exposes_common_oauth_options() -> None:
    settings = GoogleOAuth(
        client_id="google-client-id",
        client_secret="google-client-secret",
        response_mode="form_post",
        state_strategy="cookie",
        use_pkce=False,
        use_nonce=False,
        token_params={"prompt": "select_account"},
        discovery_headers={"x-test": "1"},
    )

    provider = settings.to_provider()

    assert provider.response_mode == "form_post"
    assert provider.state_strategy == "cookie"
    assert provider.use_pkce is False
    assert provider.use_nonce is False
    assert provider.token_params == {"prompt": "select_account"}
    assert provider.discovery_headers == {"x-test": "1"}


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
    assert query["include_granted_scopes"][0] == "true"
    assert query["scope"][0] == "openid email profile"


@pytest.mark.asyncio
async def test_google_authorization_url_uses_primary_client_id_from_list() -> None:
    plugin = _build_plugin(
        GoogleOAuth(
            client_id=["google-web-client-id", "google-ios-client-id"],
            client_secret="google-client-secret",
        ),
    )
    plugin.resolve_server_metadata = AsyncMock(  # type: ignore[attr-defined]
        return_value={"authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth"},
    )

    url = await plugin.generate_authorization_url("test-state", code_verifier="verifier", nonce="nonce")
    query = parse_qs(urlparse(url).query)

    assert query["client_id"][0] == "google-web-client-id"


def test_google_hosted_domain_becomes_authorization_param() -> None:
    settings = GoogleOAuth(
        client_id="google-client-id",
        client_secret="google-client-secret",
        hosted_domain="example.com",
    )

    provider = settings.to_provider()

    assert provider.authorization_params["hd"] == "example.com"


def test_google_plugin_exposes_stable_endpoint_constants() -> None:
    assert GoogleOAuthPlugin.DISCOVERY_URL == "https://accounts.google.com/.well-known/openid-configuration"
    assert GoogleOAuthPlugin.TOKEN_URL == "https://oauth2.googleapis.com/token"  # noqa: S105
    assert GoogleOAuthPlugin.USER_INFO_URL == "https://openidconnect.googleapis.com/v1/userinfo"


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


def test_google_userinfo_model_accepts_legacy_google_fields() -> None:
    profile = GoogleUserInfo(
        id="google-user-1",
        email="person@example.com",
        verified_email=True,
    )

    assert profile.resolved_subject == "google-user-1"
    assert profile.resolved_email_verified is True


@pytest.mark.asyncio
@respx.mock
async def test_google_profile_prefers_verified_id_token_claims_before_userinfo() -> None:
    plugin = _build_plugin()
    signing_key = build_rsa_signing_key(kid="google-key")
    issuer = "https://accounts.google.com"
    nonce = "google-nonce"
    id_token = issue_id_token(
        signing_key=signing_key,
        issuer=issuer,
        audience="google-client-id",
        subject="google-user-1",
        nonce=nonce,
        claims={
            "email": "person@example.com",
            "email_verified": True,
            "name": "Test Person",
            "picture": "https://example.com/photo.jpg",
        },
    )

    respx.get(GoogleOAuth.DISCOVERY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "issuer": issuer,
                "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_endpoint": GoogleOAuthPlugin.TOKEN_URL,
                "userinfo_endpoint": GoogleOAuthPlugin.USER_INFO_URL,
                "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
            },
        ),
    )
    respx.post(GoogleOAuthPlugin.TOKEN_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "google-access-token",
                "refresh_token": "google-refresh-token",
                "token_type": "Bearer",
                "expires_in": 3600,
                "id_token": id_token,
            },
        ),
    )
    respx.get("https://www.googleapis.com/oauth2/v3/certs").mock(
        return_value=httpx.Response(200, json=build_jwks_document(signing_key)),
    )
    userinfo_route = respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "sub": "google-user-1",
                "email": "other@example.com",
                "email_verified": False,
            },
        ),
    )

    token_set = await plugin._transport.exchange_code_for_tokens("auth-code", code_verifier="verifier")
    profile = await plugin._transport.fetch_provider_profile(token_set, nonce=nonce)

    assert userinfo_route.called is False
    assert profile.provider_account_id == "google-user-1"
    assert profile.email == "person@example.com"
    assert profile.email_verified is True
    assert profile.name == "Test Person"


@pytest.mark.asyncio
@respx.mock
async def test_google_profile_accepts_secondary_client_id_audience() -> None:
    plugin = _build_plugin(
        GoogleOAuth(
            client_id=["google-web-client-id", "google-ios-client-id"],
            client_secret="google-client-secret",
        ),
    )
    signing_key = build_rsa_signing_key(kid="google-key")
    issuer = "https://accounts.google.com"
    nonce = "google-nonce"
    id_token = issue_id_token(
        signing_key=signing_key,
        issuer=issuer,
        audience="google-ios-client-id",
        subject="google-user-1",
        nonce=nonce,
        claims={
            "email": "person@example.com",
            "email_verified": True,
            "name": "Test Person",
        },
    )

    respx.get(GoogleOAuth.DISCOVERY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "issuer": issuer,
                "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_endpoint": GoogleOAuthPlugin.TOKEN_URL,
                "userinfo_endpoint": GoogleOAuthPlugin.USER_INFO_URL,
                "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
            },
        ),
    )
    respx.get("https://www.googleapis.com/oauth2/v3/certs").mock(
        return_value=httpx.Response(200, json=build_jwks_document(signing_key)),
    )

    profile = await plugin._transport.fetch_provider_profile(
        OAuthTokenSet.from_response(
            {
                "access_token": "google-access-token",
                "token_type": "Bearer",
                "id_token": id_token,
                "expires_in": 3600,
            },
        ),
        nonce=nonce,
    )

    assert profile.provider_account_id == "google-user-1"
    assert profile.email == "person@example.com"
    assert profile.email_verified is True


@pytest.mark.asyncio
@respx.mock
async def test_google_profile_falls_back_to_userinfo_without_id_token() -> None:
    plugin = _build_plugin()

    respx.get(GoogleOAuth.DISCOVERY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "issuer": "https://accounts.google.com",
                "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_endpoint": GoogleOAuthPlugin.TOKEN_URL,
                "userinfo_endpoint": GoogleOAuthPlugin.USER_INFO_URL,
                "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
            },
        ),
    )
    userinfo_route = respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "sub": "google-user-2",
                "email": "fallback@example.com",
                "email_verified": True,
                "name": "Fallback User",
                "picture": "https://example.com/fallback.jpg",
            },
        ),
    )

    token_set = OAuthTokenSet.from_response(
        {
            "access_token": "google-access-token",
            "token_type": "Bearer",
        },
    )
    profile = await plugin._transport.fetch_provider_profile(token_set)

    assert userinfo_route.called is True
    assert profile.provider_account_id == "google-user-2"
    assert profile.email == "fallback@example.com"
    assert profile.email_verified is True
