from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
from pydantic import ValidationError

from belgie.core.exceptions import OAuthError
from belgie.providers.google import GoogleOAuthProvider, GoogleTokenResponse, GoogleUserInfo


@pytest.fixture
def google_provider() -> GoogleOAuthProvider:
    return GoogleOAuthProvider(
        client_id="test-client-id",
        client_secret="test-client-secret",  # noqa: S106
        redirect_uri="http://localhost:8000/callback",
        scopes=["openid", "email", "profile"],
    )


def test_google_token_response_dataclass() -> None:
    token = GoogleTokenResponse(
        access_token="test_access",  # noqa: S106
        expires_in=3600,
        token_type="Bearer",  # noqa: S106
        scope="openid email",
        refresh_token="test_refresh",  # noqa: S106
        id_token="test_id_token",  # noqa: S106
    )

    assert token.access_token == "test_access"
    assert token.expires_in == 3600
    assert token.token_type == "Bearer"
    assert token.scope == "openid email"
    assert token.refresh_token == "test_refresh"
    assert token.id_token == "test_id_token"


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
        GoogleUserInfo(
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


def test_generate_authorization_url(google_provider: GoogleOAuthProvider) -> None:
    url = google_provider.generate_authorization_url("test-state-123")

    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    assert parsed.scheme == "https"
    assert parsed.netloc == "accounts.google.com"
    assert parsed.path == "/o/oauth2/v2/auth"
    assert query_params["client_id"][0] == "test-client-id"
    assert query_params["redirect_uri"][0] == "http://localhost:8000/callback"
    assert query_params["response_type"][0] == "code"
    assert query_params["scope"][0] == "openid email profile"
    assert query_params["state"][0] == "test-state-123"
    assert query_params["access_type"][0] == "offline"
    assert query_params["prompt"][0] == "consent"


def test_generate_authorization_url_with_different_state(google_provider: GoogleOAuthProvider) -> None:
    url1 = google_provider.generate_authorization_url("state1")
    url2 = google_provider.generate_authorization_url("state2")

    assert "state=state1" in url1
    assert "state=state2" in url2
    assert url1 != url2


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_success(google_provider: GoogleOAuthProvider) -> None:
    mock_response = {
        "access_token": "ya29.test_access_token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
        "refresh_token": "1//test_refresh_token",
        "id_token": "eyJhbGciOi.test_id_token",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_response))

    result = await google_provider.exchange_code_for_tokens("test-auth-code")

    assert result["access_token"] == "ya29.test_access_token"
    assert result["refresh_token"] == "1//test_refresh_token"
    assert result["token_type"] == "Bearer"
    assert result["scope"] == "openid email profile"
    assert result["id_token"] == "eyJhbGciOi.test_id_token"
    assert result["expires_at"] is not None
    assert isinstance(result["expires_at"], datetime)


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_without_refresh_token(google_provider: GoogleOAuthProvider) -> None:
    mock_response = {
        "access_token": "ya29.test_access_token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_response))

    result = await google_provider.exchange_code_for_tokens("test-auth-code")

    assert result["access_token"] == "ya29.test_access_token"
    assert result["refresh_token"] is None


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_http_error(google_provider: GoogleOAuthProvider) -> None:
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))

    with pytest.raises(OAuthError, match="oauth token exchange failed: 400"):
        await google_provider.exchange_code_for_tokens("invalid-code")


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_network_error(google_provider: GoogleOAuthProvider) -> None:
    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(side_effect=httpx.RequestError("Network error"))

    with pytest.raises(OAuthError, match="oauth token exchange request failed"):
        await google_provider.exchange_code_for_tokens("test-code")


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_missing_required_field(google_provider: GoogleOAuthProvider) -> None:
    mock_response = {
        "expires_in": 3600,
        "token_type": "Bearer",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_response))

    with pytest.raises(OAuthError, match="missing required field in token response"):
        await google_provider.exchange_code_for_tokens("test-code")


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_success(google_provider: GoogleOAuthProvider) -> None:
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
async def test_get_user_info_http_error(google_provider: GoogleOAuthProvider) -> None:
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(401, json={"error": "invalid_token"}))

    with pytest.raises(OAuthError, match="failed to fetch user info: 401"):
        await google_provider.get_user_info("invalid-token")


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_network_error(google_provider: GoogleOAuthProvider) -> None:
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(side_effect=httpx.RequestError("Network error"))

    with pytest.raises(OAuthError, match="user info request failed"):
        await google_provider.get_user_info("test-token")


@pytest.mark.asyncio
@respx.mock
async def test_get_user_info_sends_bearer_token(google_provider: GoogleOAuthProvider) -> None:
    mock_user_data = {
        "id": "123456789",
        "email": "testuser@example.com",
        "verified_email": True,
    }

    route = respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_data))

    await google_provider.get_user_info("my-access-token")

    assert route.called
    request = route.calls.last.request
    assert request.headers["Authorization"] == "Bearer my-access-token"
