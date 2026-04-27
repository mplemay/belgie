from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from belgie_core.core.settings import BelgieSettings
from belgie_oauth import MicrosoftOAuth, MicrosoftOAuthClient, MicrosoftOAuthPlugin, MicrosoftUserInfo, OAuthTokenSet
from belgie_oauth.__tests__.helpers import build_jwks_document, build_rsa_signing_key, issue_id_token
from belgie_oauth.microsoft import _map_microsoft_profile
from pydantic import SecretStr, ValidationError

MICROSOFT_CLIENT_SECRET = SecretStr("microsoft-client-secret")


def _build_plugin(settings: MicrosoftOAuth | None = None) -> MicrosoftOAuthPlugin:
    provider_settings = settings or MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret=MICROSOFT_CLIENT_SECRET,
    )
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    return MicrosoftOAuthPlugin(belgie_settings, provider_settings)


def _token_set() -> OAuthTokenSet:
    return OAuthTokenSet.from_response(
        {
            "access_token": "microsoft-access-token",
            "token_type": "Bearer",
            "expires_in": 3600,
        },
    )


def test_microsoft_settings_defaults() -> None:
    settings = MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret=MICROSOFT_CLIENT_SECRET,
    )

    assert settings.tenant == "common"
    assert settings.authority == "https://login.microsoftonline.com"
    assert settings.profile_photo_size == 48
    assert settings.scopes == ["openid", "profile", "email", "offline_access", "User.Read"]


def test_microsoft_settings_reject_empty_tenant() -> None:
    with pytest.raises(ValidationError):
        MicrosoftOAuth(
            client_id="microsoft-client-id",
            client_secret=MICROSOFT_CLIENT_SECRET,
            tenant="",
        )


def test_microsoft_settings_reject_empty_client_id_list() -> None:
    with pytest.raises(ValidationError):
        MicrosoftOAuth(
            client_id=[],
            client_secret=MICROSOFT_CLIENT_SECRET,
        )


def test_microsoft_common_tenant_preset_uses_graph_userinfo() -> None:
    settings = MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret=MICROSOFT_CLIENT_SECRET,
    )
    provider = settings.provider

    assert provider.authorization_endpoint == "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
    assert provider.token_endpoint == "https://login.microsoftonline.com/common/oauth2/v2.0/token"  # noqa: S105
    assert provider.userinfo_endpoint == "https://graph.microsoft.com/oidc/userinfo"
    assert provider.issuer is None


def test_microsoft_public_client_mode_uses_none_auth() -> None:
    settings = MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret=None,
    )
    provider = settings.provider

    assert provider.client_secret is None
    assert provider.token_endpoint_auth_method == "none"  # noqa: S105


def test_microsoft_tenant_specific_preset_sets_expected_issuer() -> None:
    settings = MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret=MICROSOFT_CLIENT_SECRET,
        tenant="tenant-123",
    )
    provider = settings.provider

    assert provider.issuer == "https://login.microsoftonline.com/tenant-123/v2.0"
    assert provider.jwks_uri == "https://login.microsoftonline.com/tenant-123/discovery/v2.0/keys"


def test_microsoft_provider_is_cached_and_plugin_uses_client_classvar() -> None:
    settings = MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret=MICROSOFT_CLIENT_SECRET,
    )

    provider = settings.provider
    plugin = _build_plugin(settings)

    assert settings.provider is provider
    assert MicrosoftOAuthPlugin.__dict__.get("__init__") is None
    assert plugin.client_type is MicrosoftOAuthClient


def test_microsoft_preset_exposes_common_oauth_options() -> None:
    settings = MicrosoftOAuth(
        client_id="microsoft-client-id",
        client_secret=MICROSOFT_CLIENT_SECRET,
        response_mode="form_post",
        state_strategy="cookie",
        use_pkce=False,
        use_nonce=False,
        disable_id_token_sign_in=True,
        store_account_cookie=True,
        default_error_redirect_url="/oauth-error",
        token_params={"resource": "https://graph.microsoft.com"},
        discovery_headers={"x-test": "1"},
    )

    provider = settings.provider

    assert provider.response_mode == "form_post"
    assert provider.state_strategy == "cookie"
    assert provider.use_pkce is False
    assert provider.use_nonce is False
    assert provider.disable_id_token_sign_in is True
    assert provider.store_account_cookie is True
    assert provider.default_error_redirect_url == "/oauth-error"
    assert provider.token_params == {"resource": "https://graph.microsoft.com"}
    assert provider.discovery_headers == {"x-test": "1"}


def test_microsoft_settings_reject_invalid_profile_photo_size() -> None:
    with pytest.raises(ValidationError):
        MicrosoftOAuth(
            client_id="microsoft-client-id",
            client_secret=MICROSOFT_CLIENT_SECRET,
            profile_photo_size=72,
        )


@pytest.mark.asyncio
async def test_microsoft_authorization_url_includes_query_response_mode() -> None:
    plugin = _build_plugin()

    url = await plugin.generate_authorization_url("test-state", code_verifier="verifier", nonce="nonce")
    query = parse_qs(urlparse(url).query)

    assert query["response_mode"][0] == "query"
    assert query["scope"][0] == "openid profile email offline_access User.Read"


@pytest.mark.asyncio
async def test_microsoft_authorization_url_uses_primary_client_id_from_list() -> None:
    plugin = _build_plugin(
        MicrosoftOAuth(
            client_id=["microsoft-web-client-id", "microsoft-native-client-id"],
            client_secret=MICROSOFT_CLIENT_SECRET,
        ),
    )

    url = await plugin.generate_authorization_url("test-state", code_verifier="verifier", nonce="nonce")
    query = parse_qs(urlparse(url).query)

    assert query["client_id"][0] == "microsoft-web-client-id"


@pytest.mark.asyncio
@respx.mock
async def test_microsoft_refresh_reuses_existing_or_default_scope() -> None:
    plugin = _build_plugin()
    refresh_route = respx.post("https://login.microsoftonline.com/common/oauth2/v2.0/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "fresh-access-token",
                "token_type": "Bearer",
                "expires_in": 3600,
            },
        ),
    )
    token_set = OAuthTokenSet.from_response(
        {
            "access_token": "stale-access-token",
            "refresh_token": "refresh-token",
            "token_type": "Bearer",
            "scope": "openid email profile",
            "expires_in": 1,
        },
    )

    await plugin._transport.refresh_token_set(token_set)

    body = refresh_route.calls.last.request.content.decode("utf-8")
    assert parse_qs(body)["scope"] == ["openid email profile"]


def test_microsoft_profile_mapper_falls_back_to_preferred_username() -> None:
    mapped = _map_microsoft_profile(
        {
            "sub": "microsoft-user-1",
            "preferred_username": "person@example.com",
            "name": "Microsoft Person",
        },
        token_set=_token_set(),
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


def test_microsoft_userinfo_model_uses_verified_email_lists() -> None:
    profile = MicrosoftUserInfo(
        sub="microsoft-user-1",
        verified_primary_email=["person@example.com"],
    )

    assert profile.resolved_email == "person@example.com"
    assert profile.resolved_email_verified is True


@pytest.mark.asyncio
@respx.mock
async def test_microsoft_profile_uses_graph_userinfo_and_photo_enrichment() -> None:
    plugin = _build_plugin(
        MicrosoftOAuth(
            client_id="microsoft-client-id",
            client_secret=MICROSOFT_CLIENT_SECRET,
            tenant="tenant-123",
            profile_photo_size=96,
        ),
    )
    signing_key = build_rsa_signing_key(kid="microsoft-key")
    issuer = "https://login.microsoftonline.com/tenant-123/v2.0"
    nonce = "microsoft-nonce"
    id_token = issue_id_token(
        signing_key=signing_key,
        issuer=issuer,
        audience="microsoft-client-id",
        subject="microsoft-user-1",
        nonce=nonce,
        claims={"name": "ID Token Name"},
    )

    respx.get("https://login.microsoftonline.com/tenant-123/discovery/v2.0/keys").mock(
        return_value=httpx.Response(200, json=build_jwks_document(signing_key)),
    )
    userinfo_route = respx.get(MicrosoftOAuthPlugin.USER_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "sub": "microsoft-user-1",
                "preferred_username": "person@example.com",
                "name": "Graph User",
            },
        ),
    )
    photo_route = respx.get(MicrosoftOAuthPlugin.profile_photo_url(96)).mock(
        return_value=httpx.Response(
            200,
            content=b"image-bytes",
            headers={"content-type": "image/png"},
        ),
    )

    token_set = OAuthTokenSet.from_response(
        {
            "access_token": "microsoft-access-token",
            "token_type": "Bearer",
            "id_token": id_token,
            "expires_in": 3600,
        },
    )
    profile = await plugin._transport.fetch_provider_profile(token_set, nonce=nonce)

    assert userinfo_route.called is True
    assert photo_route.called is True
    assert profile.provider_account_id == "microsoft-user-1"
    assert profile.email == "person@example.com"
    assert profile.email_verified is False
    assert profile.name == "Graph User"
    assert profile.image is not None
    assert profile.image.startswith("data:image/png;base64,")


@pytest.mark.asyncio
@respx.mock
async def test_microsoft_profile_accepts_secondary_client_id_audience() -> None:
    plugin = _build_plugin(
        MicrosoftOAuth(
            client_id=["microsoft-web-client-id", "microsoft-native-client-id"],
            client_secret=MICROSOFT_CLIENT_SECRET,
            tenant="tenant-123",
            disable_profile_photo=True,
        ),
    )
    signing_key = build_rsa_signing_key(kid="microsoft-key")
    issuer = "https://login.microsoftonline.com/tenant-123/v2.0"
    nonce = "microsoft-nonce"
    id_token = issue_id_token(
        signing_key=signing_key,
        issuer=issuer,
        audience="microsoft-native-client-id",
        subject="microsoft-user-1",
        nonce=nonce,
        claims={"name": "ID Token Name"},
    )

    respx.get("https://login.microsoftonline.com/tenant-123/discovery/v2.0/keys").mock(
        return_value=httpx.Response(200, json=build_jwks_document(signing_key)),
    )
    respx.get(MicrosoftOAuthPlugin.USER_INFO_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "sub": "microsoft-user-1",
                "preferred_username": "person@example.com",
                "name": "Graph User",
            },
        ),
    )

    profile = await plugin._transport.fetch_provider_profile(
        OAuthTokenSet.from_response(
            {
                "access_token": "microsoft-access-token",
                "token_type": "Bearer",
                "id_token": id_token,
                "expires_in": 3600,
            },
        ),
        nonce=nonce,
    )

    assert profile.provider_account_id == "microsoft-user-1"
    assert profile.email == "person@example.com"
    assert profile.name == "Graph User"
