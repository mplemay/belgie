from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from belgie_core.core.exceptions import OAuthError
from belgie_core.core.settings import BelgieSettings
from belgie_oauth import MicrosoftOAuth, MicrosoftOAuthPlugin, MicrosoftUserInfo
from pydantic import ValidationError

from belgie.oauth.microsoft import MicrosoftOAuth as BelgieMicrosoftOAuth


@pytest.fixture
def microsoft_provider_settings() -> MicrosoftOAuth:
    return MicrosoftOAuth(
        client_id="test-client-id",
        client_secret="test-client-secret",
    )


@pytest.fixture
def belgie_settings() -> BelgieSettings:
    return BelgieSettings(secret="test-secret", base_url="http://localhost:8000")


@pytest.fixture
def microsoft_provider(
    microsoft_provider_settings: MicrosoftOAuth,
    belgie_settings: BelgieSettings,
) -> MicrosoftOAuthPlugin:
    return MicrosoftOAuthPlugin(belgie_settings, microsoft_provider_settings)


def test_microsoft_reexports_match() -> None:
    assert MicrosoftOAuth is BelgieMicrosoftOAuth


def test_microsoft_user_info_valid() -> None:
    user_info = MicrosoftUserInfo(
        sub="123456",
        email="test@example.com",
        preferred_username="test@example.com",
        name="Test Individual",
        given_name="Test",
        family_name="Individual",
        picture="https://example.com/photo.jpg",
    )

    assert user_info.sub == "123456"
    assert user_info.email == "test@example.com"
    assert user_info.resolved_email == "test@example.com"
    assert user_info.name == "Test Individual"


def test_microsoft_user_info_prefers_preferred_username() -> None:
    user_info = MicrosoftUserInfo(
        sub="123456",
        preferred_username="alias@example.com",
    )

    assert user_info.resolved_email == "alias@example.com"


def test_microsoft_user_info_missing_required_field() -> None:
    with pytest.raises(ValidationError):
        MicrosoftUserInfo(  # type: ignore[call-arg]
            email="test@example.com",
        )


def test_microsoft_provider_id(microsoft_provider: MicrosoftOAuthPlugin) -> None:
    assert microsoft_provider.provider_id == "microsoft"


def test_microsoft_provider_settings_defaults() -> None:
    settings = MicrosoftOAuth(
        client_id="test-client-id",
        client_secret="test-secret",
    )

    assert settings.client_id == "test-client-id"
    assert settings.client_secret.get_secret_value() == "test-secret"
    assert settings.tenant == "common"
    assert settings.scopes == ["openid", "profile", "email", "offline_access", "Individual.Read"]


def test_microsoft_provider_settings_custom_values() -> None:
    settings = MicrosoftOAuth(
        client_id="custom-client-id",
        client_secret="custom-secret",
        tenant="organizations",
        scopes=["openid", "email"],
    )

    assert settings.tenant == "organizations"
    assert settings.scopes == ["openid", "email"]


def test_microsoft_provider_settings_reads_scopes_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_MICROSOFT_SCOPES", "openid,profile,email,offline_access,Individual.Read")

    settings = MicrosoftOAuth(
        client_id="test-client-id",
        client_secret="test-secret",
    )

    assert settings.scopes == ["openid", "profile", "email", "offline_access", "Individual.Read"]


def test_microsoft_provider_settings_rejects_empty_client_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        MicrosoftOAuth(
            client_id="",
            client_secret="test-secret",
        )

    errors = exc_info.value.errors()
    assert any(error["loc"][0] == "client_id" for error in errors)
    assert any("non-empty" in str(error["msg"]).lower() for error in errors)


def test_microsoft_provider_settings_rejects_empty_client_secret() -> None:
    with pytest.raises(ValidationError) as exc_info:
        MicrosoftOAuth(
            client_id="test-client-id",
            client_secret="",
        )

    errors = exc_info.value.errors()
    assert any(error["loc"][0] == "client_secret" for error in errors)


def test_microsoft_provider_settings_rejects_empty_tenant() -> None:
    with pytest.raises(ValidationError) as exc_info:
        MicrosoftOAuth(
            client_id="test-client-id",
            client_secret="test-secret",
            tenant="",
        )

    errors = exc_info.value.errors()
    assert any(error["loc"][0] == "tenant" for error in errors)


def test_microsoft_provider_redirect_uri_is_derived_from_base_url(
    microsoft_provider: MicrosoftOAuthPlugin,
) -> None:
    assert microsoft_provider.redirect_uri == "http://localhost:8000/auth/provider/microsoft/callback"


def test_microsoft_provider_redirect_uri_includes_base_path(
    microsoft_provider_settings: MicrosoftOAuth,
) -> None:
    plugin = MicrosoftOAuthPlugin(
        BelgieSettings(secret="test-secret", base_url="http://localhost:8000/app"),
        microsoft_provider_settings,
    )

    assert plugin.redirect_uri == "http://localhost:8000/app/auth/provider/microsoft/callback"


def test_generate_authorization_url_format() -> None:
    plugin = MicrosoftOAuthPlugin(
        BelgieSettings(secret="test-secret", base_url="http://localhost:8000"),
        MicrosoftOAuth(
            client_id="test-client-id",
            client_secret="test-secret",
            tenant="organizations",
        ),
    )

    state = "test-state-123"
    url = plugin.generate_authorization_url(state)

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "login.microsoftonline.com"
    assert parsed.path == "/organizations/oauth2/v2.0/authorize"
    assert query_params["client_id"][0] == plugin.settings.client_id
    assert query_params["redirect_uri"][0] == plugin.redirect_uri
    assert query_params["response_type"][0] == "code"
    assert query_params["response_mode"][0] == "query"
    assert query_params["scope"][0] == "openid profile email offline_access Individual.Read"
    assert query_params["state"][0] == state


def test_generate_authorization_url_unique_states(microsoft_provider: MicrosoftOAuthPlugin) -> None:
    url1 = microsoft_provider.generate_authorization_url("state1")
    url2 = microsoft_provider.generate_authorization_url("state2")

    assert "state=state1" in url1
    assert "state=state2" in url2
    assert url1 != url2


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_success(microsoft_provider: MicrosoftOAuthPlugin) -> None:
    mock_response = {
        "access_token": "ya29.test_access_token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid profile email offline_access Individual.Read",
        "refresh_token": "1//test_refresh_token",
        "id_token": "eyJhbGciOi.test_id_token",
    }

    respx.post(microsoft_provider.token_url).mock(return_value=httpx.Response(200, json=mock_response))

    result = await microsoft_provider.exchange_code_for_tokens("test-code")

    assert result["access_token"] == "ya29.test_access_token"  # noqa: S105
    assert result["token_type"] == "Bearer"  # noqa: S105
    assert result["scope"] == "openid profile email offline_access Individual.Read"
    assert result["refresh_token"] == "1//test_refresh_token"  # noqa: S105
    assert result["id_token"] == "eyJhbGciOi.test_id_token"  # noqa: S105
    assert result["expires_at"] is not None


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_missing_access_token(microsoft_provider: MicrosoftOAuthPlugin) -> None:
    respx.post(microsoft_provider.token_url).mock(return_value=httpx.Response(200, json={"expires_in": 3600}))

    with pytest.raises(OAuthError, match="missing required field in token response"):
        await microsoft_provider.exchange_code_for_tokens("test-code")


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_success(microsoft_provider: MicrosoftOAuthPlugin) -> None:
    mock_user_data = {
        "sub": "123456789",
        "email": "testuser@example.com",
        "preferred_username": "testuser@example.com",
        "name": "Test Individual",
        "given_name": "Test",
        "family_name": "Individual",
        "picture": "https://graph.microsoft.com/photo.jpg",
    }

    respx.get(microsoft_provider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_data))

    user_info = await microsoft_provider.get_user_info("test-access-token")

    assert isinstance(user_info, MicrosoftUserInfo)
    assert user_info.sub == "123456789"
    assert user_info.email == "testuser@example.com"
    assert user_info.resolved_email == "testuser@example.com"
    assert user_info.name == "Test Individual"
    assert user_info.picture == "https://graph.microsoft.com/photo.jpg"


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_minimal_data(microsoft_provider: MicrosoftOAuthPlugin) -> None:
    mock_user_data = {
        "sub": "123456789",
        "preferred_username": "minimal@example.com",
    }

    respx.get(microsoft_provider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_data))

    user_info = await microsoft_provider.get_user_info("test-access-token")

    assert user_info.sub == "123456789"
    assert user_info.resolved_email == "minimal@example.com"
    assert user_info.name is None


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_sends_bearer_token(microsoft_provider: MicrosoftOAuthPlugin) -> None:
    mock_user_data = {
        "sub": "123",
        "preferred_username": "test@example.com",
    }

    route = respx.get(microsoft_provider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_data))

    await microsoft_provider.get_user_info("my-access-token")

    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer my-access-token"
