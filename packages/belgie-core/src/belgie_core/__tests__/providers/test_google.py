from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from belgie_core.core.exceptions import OAuthError
from belgie_core.providers.google import GoogleOAuthProvider, GoogleProviderSettings, GoogleUserInfo
from pydantic import ValidationError


@pytest.fixture
def google_provider_settings() -> GoogleProviderSettings:
    return GoogleProviderSettings(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8000/callback",
        scopes=["openid", "email", "profile"],
    )


@pytest.fixture
def google_provider(google_provider_settings: GoogleProviderSettings) -> GoogleOAuthProvider:
    return GoogleOAuthProvider(settings=google_provider_settings)


def test_google_user_info_valid() -> None:
    user_info = GoogleUserInfo(
        id="123456",
        email="test@example.com",
        verified_email=True,
        name="Test User",
        given_name="Test",
        family_name="User",
        picture="https://example.com/photo.jpg",
        locale="en",
    )

    assert user_info.id == "123456"
    assert user_info.email == "test@example.com"
    assert user_info.verified_email is True
    assert user_info.name == "Test User"


def test_google_user_info_required_fields_only() -> None:
    user_info = GoogleUserInfo(
        id="123456",
        email="test@example.com",
        verified_email=True,
    )

    assert user_info.id == "123456"
    assert user_info.email == "test@example.com"
    assert user_info.name is None
    assert user_info.picture is None


def test_google_user_info_missing_required_field() -> None:
    with pytest.raises(ValidationError):
        GoogleUserInfo(  # type: ignore[call-arg]
            id="123456",
            email="test@example.com",
        )


def test_google_user_info_extra_fields_ignored() -> None:
    user_info = GoogleUserInfo(
        id="123456",
        email="test@example.com",
        verified_email=True,
        extra_field="should be ignored",  # type: ignore[call-arg]
    )

    assert user_info.id == "123456"
    assert not hasattr(user_info, "extra_field")


def test_google_provider_id(google_provider: GoogleOAuthProvider) -> None:
    assert google_provider.provider_id == "google"


def test_google_provider_settings() -> None:
    settings = GoogleProviderSettings(
        client_id="test-client-id",
        client_secret="test-secret",
        redirect_uri="http://localhost:8000/auth/callback/google",
    )

    assert settings.client_id == "test-client-id"
    assert settings.client_secret.get_secret_value() == "test-secret"
    assert settings.redirect_uri == "http://localhost:8000/auth/callback/google"
    assert settings.scopes == ["openid", "email", "profile"]
    assert settings.access_type == "offline"
    assert settings.prompt == "consent"


def test_google_provider_settings_custom_values() -> None:
    settings = GoogleProviderSettings(
        client_id="custom-client-id",
        client_secret="custom-secret",
        redirect_uri="http://example.com/callback",
        scopes=["openid", "email"],
        access_type="online",
        prompt="select_account",
    )

    assert settings.scopes == ["openid", "email"]
    assert settings.access_type == "online"
    assert settings.prompt == "select_account"


def test_google_provider_settings_rejects_empty_client_id() -> None:
    """Verify that empty client_id is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        GoogleProviderSettings(
            client_id="",
            client_secret="test-secret",
            redirect_uri="http://localhost:8000/callback",
        )

    errors = exc_info.value.errors()
    assert any(error["loc"][0] == "client_id" for error in errors)
    assert any("non-empty" in str(error["msg"]).lower() for error in errors)


def test_google_provider_settings_rejects_empty_client_secret() -> None:
    """Verify that empty client_secret is rejected."""
    with pytest.raises(ValidationError) as exc_info:
        GoogleProviderSettings(
            client_id="test-client-id",
            client_secret="",
            redirect_uri="http://localhost:8000/callback",
        )

    errors = exc_info.value.errors()
    assert any(error["loc"][0] == "client_secret" for error in errors)


def test_google_provider_settings_rejects_whitespace_only() -> None:
    """Verify that whitespace-only strings are rejected."""
    with pytest.raises(ValidationError) as exc_info:
        GoogleProviderSettings(
            client_id="test-client-id",
            client_secret="test-secret",
            redirect_uri="   ",
        )

    errors = exc_info.value.errors()
    assert any(error["loc"][0] == "redirect_uri" for error in errors)


def test_google_provider_settings_trims_whitespace() -> None:
    """Verify that leading/trailing whitespace is trimmed."""
    settings = GoogleProviderSettings(
        client_id="  test-client-id  ",
        client_secret="  test-secret  ",
        redirect_uri="  http://localhost:8000/callback  ",
    )

    assert settings.client_id == "test-client-id"
    assert settings.client_secret.get_secret_value() == "test-secret"
    assert settings.redirect_uri == "http://localhost:8000/callback"


# Authorization URL Generation Tests


def test_generate_authorization_url_format(google_provider: GoogleOAuthProvider) -> None:
    """Verify authorization URL contains all required OAuth parameters."""
    state = "test-state-123"
    url = google_provider.generate_authorization_url(state)

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parsed.path == "/o/oauth2/v2/auth"
    assert query_params["client_id"][0] == google_provider.settings.client_id
    assert query_params["redirect_uri"][0] == google_provider.settings.redirect_uri
    assert query_params["response_type"][0] == "code"
    assert query_params["scope"][0] == "openid email profile"
    assert query_params["state"][0] == state
    assert query_params["access_type"][0] == "offline"
    assert query_params["prompt"][0] == "consent"


def test_generate_authorization_url_unique_states(google_provider: GoogleOAuthProvider) -> None:
    """Verify different states produce different URLs."""
    url1 = google_provider.generate_authorization_url("state1")
    url2 = google_provider.generate_authorization_url("state2")

    assert "state=state1" in url1
    assert "state=state2" in url2
    assert url1 != url2


# Token Exchange Error Handling Tests


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_success(google_provider: GoogleOAuthProvider) -> None:
    """Verify successful token exchange."""
    mock_response = {
        "access_token": "ya29.test_access_token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
        "refresh_token": "1//test_refresh_token",
        "id_token": "eyJhbGciOi.test_id_token",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_response))

    result = await google_provider.exchange_code_for_tokens("test-code")

    assert result["access_token"] == "ya29.test_access_token"  # noqa: S105
    assert result["token_type"] == "Bearer"  # noqa: S105
    assert result["scope"] == "openid email profile"
    assert result["refresh_token"] == "1//test_refresh_token"  # noqa: S105
    assert result["id_token"] == "eyJhbGciOi.test_id_token"  # noqa: S105
    assert result["expires_at"] is not None


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_http_400_error(google_provider: GoogleOAuthProvider) -> None:
    """Verify proper error handling when Google returns 400."""
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant"}),
    )

    with pytest.raises(OAuthError, match="oauth token exchange failed: 400"):
        await google_provider.exchange_code_for_tokens("invalid-code")


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_includes_error_code_in_message(google_provider: GoogleOAuthProvider) -> None:
    """Verify error message includes OAuth error code when present."""
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "Bad Request"}),
    )

    with pytest.raises(OAuthError, match=r"oauth token exchange failed: 400 \(invalid_grant\)"):
        await google_provider.exchange_code_for_tokens("invalid-code")


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_handles_non_json_error_response(google_provider: GoogleOAuthProvider) -> None:
    """Verify error handling when response is not JSON."""
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(
        return_value=httpx.Response(500, text="Internal Server Error"),
    )

    # Should still raise error without crashing when trying to parse JSON
    with pytest.raises(OAuthError, match="oauth token exchange failed: 500"):
        await google_provider.exchange_code_for_tokens("test-code")


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_network_error(google_provider: GoogleOAuthProvider) -> None:
    """Verify proper error handling on network failures."""
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(
        side_effect=httpx.RequestError("Network unreachable"),
    )

    with pytest.raises(OAuthError, match="oauth token exchange request failed"):
        await google_provider.exchange_code_for_tokens("test-code")


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_missing_access_token(google_provider: GoogleOAuthProvider) -> None:
    """Verify error when response missing required access_token field."""
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(
        return_value=httpx.Response(200, json={"expires_in": 3600}),
    )

    with pytest.raises(OAuthError, match="missing required field in token response"):
        await google_provider.exchange_code_for_tokens("test-code")


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_without_refresh_token(google_provider: GoogleOAuthProvider) -> None:
    """Verify handling when refresh_token is not provided."""
    mock_response = {
        "access_token": "ya29.test_access_token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_response))

    result = await google_provider.exchange_code_for_tokens("test-code")

    assert result["access_token"] == "ya29.test_access_token"  # noqa: S105
    assert result["refresh_token"] is None


# User Info Fetch Error Handling Tests


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_success(google_provider: GoogleOAuthProvider) -> None:
    """Verify successful user info fetch."""
    mock_user_data = {
        "id": "123456789",
        "email": "testuser@example.com",
        "verified_email": True,
        "name": "Test User",
        "given_name": "Test",
        "family_name": "User",
        "picture": "https://lh3.googleusercontent.com/photo.jpg",
        "locale": "en",
    }

    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_data))

    user_info = await google_provider.get_user_info("test-access-token")

    assert isinstance(user_info, GoogleUserInfo)
    assert user_info.id == "123456789"
    assert user_info.email == "testuser@example.com"
    assert user_info.verified_email is True
    assert user_info.name == "Test User"
    assert user_info.given_name == "Test"
    assert user_info.picture == "https://lh3.googleusercontent.com/photo.jpg"


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_minimal_data(google_provider: GoogleOAuthProvider) -> None:
    """Verify user info fetch with only required fields."""
    mock_user_data = {
        "id": "123456789",
        "email": "testuser@example.com",
        "verified_email": True,
    }

    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_data))

    user_info = await google_provider.get_user_info("test-access-token")

    assert user_info.id == "123456789"
    assert user_info.email == "testuser@example.com"
    assert user_info.name is None


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_http_401_error(google_provider: GoogleOAuthProvider) -> None:
    """Verify proper error handling when token is invalid."""
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"}),
    )

    with pytest.raises(OAuthError, match="failed to fetch user info: 401"):
        await google_provider.get_user_info("invalid-token")


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_includes_error_code_in_message(google_provider: GoogleOAuthProvider) -> None:
    """Verify error message includes OAuth error code when present."""
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"}),
    )

    with pytest.raises(OAuthError, match=r"failed to fetch user info: 401 \(invalid_token\)"):
        await google_provider.get_user_info("invalid-token")


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_handles_non_json_error_response(google_provider: GoogleOAuthProvider) -> None:
    """Verify error handling when response is not JSON."""
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(
        return_value=httpx.Response(503, text="Service Unavailable"),
    )

    # Should still raise error without crashing when trying to parse JSON
    with pytest.raises(OAuthError, match="failed to fetch user info: 503"):
        await google_provider.get_user_info("test-token")


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_network_error(google_provider: GoogleOAuthProvider) -> None:
    """Verify proper error handling on network failures."""
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(
        side_effect=httpx.RequestError("Connection timeout"),
    )

    with pytest.raises(OAuthError, match="user info request failed"):
        await google_provider.get_user_info("test-token")


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_sends_bearer_token(google_provider: GoogleOAuthProvider) -> None:
    """Verify correct Authorization header is sent."""
    mock_user_data = {
        "id": "123",
        "email": "test@example.com",
        "verified_email": True,
    }

    route = respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(
        return_value=httpx.Response(200, json=mock_user_data),
    )

    await google_provider.get_user_info("my-access-token")

    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer my-access-token"


# Integration Tests for Complete OAuth Callback Flow


@pytest.mark.asyncio
@respx.mock
async def test_complete_oauth_flow_new_user(google_provider: GoogleOAuthProvider) -> None:
    """Test complete OAuth flow from code exchange to user info fetch with new user."""
    # Mock token exchange response
    mock_token_response = {
        "access_token": "ya29.test_access_token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
        "refresh_token": "1//test_refresh_token",
        "id_token": "eyJhbGciOi.test_id_token",
    }

    # Mock user info response
    mock_user_info = {
        "id": "google-user-123",
        "email": "newuser@example.com",
        "verified_email": True,
        "name": "New User",
        "given_name": "New",
        "family_name": "User",
        "picture": "https://lh3.googleusercontent.com/photo.jpg",
        "locale": "en",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    # Execute the flow
    tokens = await google_provider.exchange_code_for_tokens("test-auth-code")
    user_info = await google_provider.get_user_info(tokens["access_token"])

    # Verify token response
    assert tokens["access_token"] == "ya29.test_access_token"  # noqa: S105
    assert tokens["refresh_token"] == "1//test_refresh_token"  # noqa: S105
    assert tokens["expires_at"] is not None

    # Verify user info
    assert user_info.id == "google-user-123"
    assert user_info.email == "newuser@example.com"
    assert user_info.verified_email is True
    assert user_info.name == "New User"
    assert user_info.picture == "https://lh3.googleusercontent.com/photo.jpg"


@pytest.mark.asyncio
@respx.mock
async def test_complete_oauth_flow_minimal_response(google_provider: GoogleOAuthProvider) -> None:
    """Test OAuth flow with minimal required fields in responses."""
    # Token response without optional fields
    mock_token_response = {
        "access_token": "ya29.minimal_token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email",
    }

    # User info with only required fields
    mock_user_info = {
        "id": "google-minimal-123",
        "email": "minimal@example.com",
        "verified_email": True,
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    # Execute the flow
    tokens = await google_provider.exchange_code_for_tokens("test-code")
    user_info = await google_provider.get_user_info(tokens["access_token"])

    # Verify minimal token response
    assert tokens["access_token"] == "ya29.minimal_token"  # noqa: S105
    assert tokens["refresh_token"] is None
    assert tokens["id_token"] is None

    # Verify minimal user info
    assert user_info.id == "google-minimal-123"
    assert user_info.email == "minimal@example.com"
    assert user_info.name is None
    assert user_info.picture is None


@pytest.mark.asyncio
@respx.mock
async def test_oauth_flow_token_exchange_fails_propagates_error(google_provider: GoogleOAuthProvider) -> None:
    """Test that token exchange errors are properly propagated."""
    # Mock failed token exchange
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(
        return_value=httpx.Response(400, json={"error": "invalid_grant", "error_description": "Code expired"}),
    )

    # Verify error is raised with status code
    with pytest.raises(OAuthError, match="oauth token exchange failed: 400"):
        await google_provider.exchange_code_for_tokens("invalid-code")


@pytest.mark.asyncio
@respx.mock
async def test_oauth_flow_user_info_fetch_fails_propagates_error(google_provider: GoogleOAuthProvider) -> None:
    """Test that user info fetch errors are properly propagated."""
    # Mock successful token exchange
    mock_token_response = {
        "access_token": "ya29.test_token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))

    # Mock failed user info fetch
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(
        return_value=httpx.Response(401, json={"error": "invalid_token"}),
    )

    # Get tokens successfully
    tokens = await google_provider.exchange_code_for_tokens("test-code")

    # Verify user info fetch fails
    with pytest.raises(OAuthError, match="failed to fetch user info: 401"):
        await google_provider.get_user_info(tokens["access_token"])


@pytest.mark.asyncio
@respx.mock
async def test_oauth_flow_network_error_during_token_exchange(google_provider: GoogleOAuthProvider) -> None:
    """Test handling of network errors during token exchange."""
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(side_effect=httpx.RequestError("Network timeout"))

    with pytest.raises(OAuthError, match="oauth token exchange request failed"):
        await google_provider.exchange_code_for_tokens("test-code")


@pytest.mark.asyncio
@respx.mock
async def test_oauth_flow_network_error_during_user_info_fetch(google_provider: GoogleOAuthProvider) -> None:
    """Test handling of network errors during user info fetch."""
    # Mock successful token exchange
    mock_token_response = {
        "access_token": "ya29.test_token",
        "expires_in": 3600,
        "token_type": "Bearer",
    }
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))

    # Mock network error during user info fetch
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(side_effect=httpx.RequestError("Connection reset"))

    tokens = await google_provider.exchange_code_for_tokens("test-code")

    with pytest.raises(OAuthError, match="user info request failed"):
        await google_provider.get_user_info(tokens["access_token"])
