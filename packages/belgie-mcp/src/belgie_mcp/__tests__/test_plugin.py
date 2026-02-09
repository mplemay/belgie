from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from belgie_core.core.settings import BelgieSettings
from belgie_mcp.plugin import McpPlugin, McpPluginSettings
from belgie_mcp.verifier import BelgieOAuthTokenVerifier
from belgie_oauth_server.settings import OAuthServerSettings


def _belgie_settings() -> BelgieSettings:
    return BelgieSettings(secret="test-secret", base_url="https://example.com")


def test_mcp_plugin_builds_auth_and_verifier() -> None:
    settings = OAuthServerSettings(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        _belgie_settings(),
        McpPluginSettings(
            oauth_settings=settings,
            server_url="https://mcp.local/mcp",
        ),
    )

    assert str(plugin.auth.issuer_url) == "https://auth.local/auth/oauth"
    assert str(plugin.auth.resource_server_url) == "https://mcp.local/mcp"
    assert isinstance(plugin.token_verifier, BelgieOAuthTokenVerifier)


def test_mcp_plugin_public_returns_none() -> None:
    settings = OAuthServerSettings(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        _belgie_settings(),
        McpPluginSettings(
            oauth_settings=settings,
            server_url="https://mcp.local/mcp",
        ),
    )

    assert plugin.public(SimpleNamespace()) is None


def test_mcp_plugin_builds_server_url_from_base_url() -> None:
    settings = OAuthServerSettings(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        _belgie_settings(),
        McpPluginSettings(
            oauth_settings=settings,
            base_url="https://example.com",
            server_path="/mcp",
        ),
    )

    assert str(plugin.auth.resource_server_url) == "https://example.com/mcp"


def test_mcp_plugin_defaults_base_url_from_belgie_settings() -> None:
    settings = OAuthServerSettings(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        _belgie_settings(),
        McpPluginSettings(
            oauth_settings=settings,
            server_path="/mcp",
        ),
    )

    assert str(plugin.auth.resource_server_url) == "https://example.com/mcp"
