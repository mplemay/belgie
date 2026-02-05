import pytest
from belgie_oauth_server.settings import OAuthSettings
from pydantic import ValidationError


def test_oauth_settings_defaults() -> None:
    settings = OAuthSettings(redirect_uris=["http://example.com/callback"])

    assert settings.route_prefix == "/oauth"
    assert settings.login_url is None
    assert settings.default_scope == "user"
    assert settings.authorization_code_ttl_seconds == 300
    assert settings.access_token_ttl_seconds == 3600
    assert settings.state_ttl_seconds == 600
    assert settings.code_challenge_method == "S256"


def test_oauth_settings_requires_redirect_uris() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthSettings()
    assert "redirect_uris" in str(exc.value)


def test_oauth_settings_rejects_empty_redirect_uris() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthSettings(redirect_uris=[])
    assert "redirect_uris" in str(exc.value)


def test_oauth_settings_populates_issuer_url_from_base_url() -> None:
    settings = OAuthSettings(
        base_url="http://example.com",
        redirect_uris=["http://example.com/callback"],
    )

    assert str(settings.issuer_url) == "http://example.com/auth/oauth"
