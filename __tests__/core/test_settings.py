import os

import pytest
from pydantic import ValidationError

from brugge.auth.core.settings import AuthSettings, CookieSettings, GoogleOAuthSettings, SessionSettings, URLSettings


def test_session_settings_defaults() -> None:
    settings = SessionSettings()

    assert settings.cookie_name == "belgie_session"
    assert settings.max_age == 604800
    assert settings.update_age == 86400


def test_session_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SESSION_COOKIE_NAME", "custom_session")
    monkeypatch.setenv("BELGIE_SESSION_MAX_AGE", "3600")
    monkeypatch.setenv("BELGIE_SESSION_UPDATE_AGE", "1800")

    settings = SessionSettings()

    assert settings.cookie_name == "custom_session"
    assert settings.max_age == 3600
    assert settings.update_age == 1800


def test_cookie_settings_defaults() -> None:
    settings = CookieSettings()

    assert settings.secure is True
    assert settings.http_only is True
    assert settings.same_site == "lax"
    assert settings.domain is None


def test_cookie_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_COOKIE_SECURE", "false")
    monkeypatch.setenv("BELGIE_COOKIE_HTTP_ONLY", "false")
    monkeypatch.setenv("BELGIE_COOKIE_SAME_SITE", "strict")
    monkeypatch.setenv("BELGIE_COOKIE_DOMAIN", "example.com")

    settings = CookieSettings()

    assert settings.secure is False
    assert settings.http_only is False
    assert settings.same_site == "strict"
    assert settings.domain == "example.com"


def test_google_oauth_settings_required_fields() -> None:
    with pytest.raises(ValidationError) as exc_info:
        GoogleOAuthSettings()  # type: ignore[call-arg]

    errors = exc_info.value.errors()  # type: ignore[attr-defined]
    field_names = {error["loc"][0] for error in errors}

    assert "client_id" in field_names
    assert "client_secret" in field_names
    assert "redirect_uri" in field_names


def test_google_oauth_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("BELGIE_GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("BELGIE_GOOGLE_REDIRECT_URI", "http://localhost:8000/callback")

    settings = GoogleOAuthSettings()  # type: ignore[call-arg]

    assert settings.client_id == "test-client-id"
    assert settings.client_secret == "test-client-secret"  # noqa: S105
    assert settings.redirect_uri == "http://localhost:8000/callback"
    assert settings.scopes == ["openid", "email", "profile"]


def test_url_settings_defaults() -> None:
    settings = URLSettings()

    assert settings.signin_redirect == "/dashboard"
    assert settings.signout_redirect == "/"


def test_url_settings_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_URLS_SIGNIN_REDIRECT", "/home")
    monkeypatch.setenv("BELGIE_URLS_SIGNOUT_REDIRECT", "/goodbye")

    settings = URLSettings()

    assert settings.signin_redirect == "/home"
    assert settings.signout_redirect == "/goodbye"


def test_auth_settings_required_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ.keys()):
        if key.startswith("BELGIE_"):
            monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError) as exc_info:
        AuthSettings()  # type: ignore[call-arg]

    errors = exc_info.value.errors()  # type: ignore[attr-defined]
    assert len(errors) > 0


def test_auth_settings_nested_google_required(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in list(os.environ.keys()):
        if key.startswith("BELGIE_"):
            monkeypatch.delenv(key, raising=False)

    with pytest.raises(ValidationError):
        AuthSettings(secret="test-secret", base_url="http://localhost:8000")  # type: ignore[call-arg]  # noqa: S106


def test_auth_settings_full_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SECRET", "super-secret-key")
    monkeypatch.setenv("BELGIE_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("BELGIE_GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setenv("BELGIE_GOOGLE_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("BELGIE_GOOGLE_REDIRECT_URI", "http://localhost:8000/callback")

    settings = AuthSettings()  # type: ignore[call-arg]

    assert settings.secret == "super-secret-key"  # noqa: S105
    assert settings.base_url == "http://localhost:8000"
    assert settings.google.client_id == "client-id"
    assert settings.google.client_secret == "client-secret"  # noqa: S105
    assert settings.google.redirect_uri == "http://localhost:8000/callback"


def test_auth_settings_nested_defaults_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SECRET", "secret")
    monkeypatch.setenv("BELGIE_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("BELGIE_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("BELGIE_GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("BELGIE_GOOGLE_REDIRECT_URI", "http://localhost:8000/callback")

    settings = AuthSettings()  # type: ignore[call-arg]

    assert settings.session.cookie_name == "belgie_session"
    assert settings.session.max_age == 604800
    assert settings.cookie.secure is True
    assert settings.urls.signin_redirect == "/dashboard"


def test_auth_settings_can_override_nested_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SECRET", "secret")
    monkeypatch.setenv("BELGIE_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("BELGIE_GOOGLE_CLIENT_ID", "id")
    monkeypatch.setenv("BELGIE_GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("BELGIE_GOOGLE_REDIRECT_URI", "http://localhost:8000/callback")
    monkeypatch.setenv("BELGIE_SESSION_MAX_AGE", "1800")
    monkeypatch.setenv("BELGIE_COOKIE_SECURE", "false")
    monkeypatch.setenv("BELGIE_URLS_SIGNIN_REDIRECT", "/home")

    settings = AuthSettings()  # type: ignore[call-arg]

    assert settings.session.max_age == 1800
    assert settings.cookie.secure is False
    assert settings.urls.signin_redirect == "/home"


def test_auth_settings_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("belgie_secret", "secret")
    monkeypatch.setenv("BELGIE_BASE_URL", "http://localhost:8000")
    monkeypatch.setenv("Belgie_Google_Client_Id", "id")
    monkeypatch.setenv("BELGIE_GOOGLE_CLIENT_SECRET", "secret")
    monkeypatch.setenv("belgie_google_redirect_uri", "http://localhost:8000/callback")

    settings = AuthSettings()  # type: ignore[call-arg]

    assert settings.secret == "secret"  # noqa: S105
    assert settings.google.client_id == "id"
