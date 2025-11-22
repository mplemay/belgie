import pytest
from pydantic import ValidationError

from belgie.auth.providers.google import GoogleOAuthProvider, GoogleProviderSettings, GoogleUserInfo


@pytest.fixture
def google_provider_settings() -> GoogleProviderSettings:
    return GoogleProviderSettings(
        client_id="test-client-id",
        client_secret="test-client-secret",  # noqa: S106
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
        client_secret="test-secret",  # noqa: S106
        redirect_uri="http://localhost:8000/auth/callback/google",
    )

    assert settings.client_id == "test-client-id"
    assert settings.client_secret == "test-secret"  # noqa: S105
    assert settings.redirect_uri == "http://localhost:8000/auth/callback/google"
    assert settings.scopes == ["openid", "email", "profile"]
    assert settings.access_type == "offline"
    assert settings.prompt == "consent"
    assert settings.session_max_age == 604800
    assert settings.cookie_name == "belgie_session"
    assert settings.signin_redirect == "/dashboard"
    assert settings.signout_redirect == "/"


def test_google_provider_settings_custom_values() -> None:
    settings = GoogleProviderSettings(
        client_id="custom-client-id",
        client_secret="custom-secret",  # noqa: S106
        redirect_uri="http://example.com/callback",
        scopes=["openid", "email"],
        access_type="online",
        prompt="select_account",
        session_max_age=3600,
        cookie_name="custom_session",
        signin_redirect="/home",
        signout_redirect="/goodbye",
    )

    assert settings.scopes == ["openid", "email"]
    assert settings.access_type == "online"
    assert settings.prompt == "select_account"
    assert settings.session_max_age == 3600
    assert settings.cookie_name == "custom_session"
    assert settings.signin_redirect == "/home"
    assert settings.signout_redirect == "/goodbye"
