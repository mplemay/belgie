import pytest
from belgie_oauth_server.settings import OAuthResource, OAuthServerSettings
from pydantic import ValidationError


def test_oauth_settings_defaults() -> None:
    settings = OAuthServerSettings(redirect_uris=["http://example.com/callback"])

    assert settings.prefix == "/oauth"
    assert settings.login_url is None
    assert settings.default_scope == "user"
    assert settings.authorization_code_ttl_seconds == 300
    assert settings.access_token_ttl_seconds == 3600
    assert settings.id_token_ttl_seconds == 36000
    assert settings.state_ttl_seconds == 600
    assert settings.code_challenge_method == "S256"
    assert settings.enable_end_session is False
    assert settings.allow_dynamic_client_registration is False
    assert settings.allow_unauthenticated_client_registration is False
    assert settings.resources is None
    assert settings.include_root_resource_metadata_fallback is True
    assert settings.include_root_openid_metadata_fallback is True


def test_oauth_settings_requires_redirect_uris() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServerSettings()
    assert "redirect_uris" in str(exc.value)


def test_oauth_settings_rejects_empty_redirect_uris() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServerSettings(redirect_uris=[])
    assert "redirect_uris" in str(exc.value)


def test_oauth_settings_rejects_legacy_route_prefix() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServerSettings(
            redirect_uris=["http://example.com/callback"],
            route_prefix="/oauth",
        )
    assert "route_prefix" in str(exc.value)


def test_oauth_settings_rejects_legacy_resource_settings() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServerSettings(
            redirect_uris=["http://example.com/callback"],
            resource_server_url="http://example.com/mcp",
        )
    assert "resource_server_url" in str(exc.value)


def test_oauth_settings_rejects_legacy_resource_scopes() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServerSettings(
            redirect_uris=["http://example.com/callback"],
            resource_scopes=["user"],
        )
    assert "resource_scopes" in str(exc.value)


def test_oauth_settings_populates_issuer_url_from_base_url() -> None:
    settings = OAuthServerSettings(
        base_url="http://example.com",
        redirect_uris=["http://example.com/callback"],
    )

    assert str(settings.issuer_url) == "http://example.com/auth/oauth"


def test_oauth_settings_accepts_resource_metadata_settings() -> None:
    settings = OAuthServerSettings(
        base_url="http://example.com",
        redirect_uris=["http://example.com/callback"],
        resources=[OAuthResource(prefix="/mcp", scopes=["user", "files:read"])],
        include_root_resource_metadata_fallback=False,
    )

    assert settings.resources is not None
    assert settings.resources[0].prefix == "/mcp"
    assert settings.resources[0].scopes == ["user", "files:read"]
    assert settings.include_root_resource_metadata_fallback is False

    resource_url, resource_scopes = settings.resolve_resource()
    assert str(resource_url) == "http://example.com/mcp"
    assert resource_scopes == ["user", "files:read"]


def test_oauth_settings_rejects_multiple_resources() -> None:
    with pytest.raises(ValidationError) as exc:
        OAuthServerSettings(
            redirect_uris=["http://example.com/callback"],
            resources=[OAuthResource(prefix="/mcp"), OAuthResource(prefix="/files")],
        )
    assert "resources" in str(exc.value)


def test_oauth_settings_resolves_resource_with_fallback_base_url() -> None:
    settings = OAuthServerSettings(
        redirect_uris=["http://example.com/callback"],
        resources=[OAuthResource(prefix="/mcp", scopes=["user"])],
    )

    resource_url, resource_scopes = settings.resolve_resource("http://example.com")
    assert str(resource_url) == "http://example.com/mcp"
    assert resource_scopes == ["user"]
