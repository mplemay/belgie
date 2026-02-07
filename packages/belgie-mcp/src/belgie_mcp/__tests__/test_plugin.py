from types import SimpleNamespace

import pytest

pytest.importorskip("mcp")

from belgie_mcp.plugin import McpPlugin
from belgie_mcp.verifier import BelgieOAuthTokenVerifier
from belgie_oauth_server.settings import OAuthSettings


def test_mcp_plugin_builds_auth_and_verifier() -> None:
    settings = OAuthSettings(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        settings,
        server_url="https://mcp.local/mcp",
    )

    assert str(plugin.auth.issuer_url) == "https://auth.local/auth/oauth"
    assert str(plugin.auth.resource_server_url) == "https://mcp.local/mcp"
    assert isinstance(plugin.token_verifier, BelgieOAuthTokenVerifier)


def test_mcp_plugin_public_returns_none() -> None:
    settings = OAuthSettings(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        settings,
        server_url="https://mcp.local/mcp",
    )

    assert plugin.public(SimpleNamespace()) is None


def test_mcp_plugin_builds_server_url_from_base_url() -> None:
    settings = OAuthSettings(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        settings,
        base_url="https://example.com",
        server_path="/mcp",
    )

    assert str(plugin.auth.resource_server_url) == "https://example.com/mcp"
