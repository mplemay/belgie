from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

from belgie_mcp.plugin import McpPlugin
from belgie_mcp.verifier import BelgieOAuthTokenVerifier
from belgie_oauth.settings import OAuthSettings


def test_mcp_plugin_builds_auth_and_verifier() -> None:
    settings = OAuthSettings(
        issuer_url="https://auth.local/oauth",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        settings,
        server_url="https://mcp.local/mcp",
    )

    assert str(plugin.auth.issuer_url) == "https://auth.local/oauth"
    assert str(plugin.auth.resource_server_url) == "https://mcp.local/mcp"
    assert isinstance(plugin.token_verifier, BelgieOAuthTokenVerifier)


def test_mcp_plugin_root_router_exposes_prm() -> None:
    settings = OAuthSettings(
        issuer_url="https://auth.local/oauth",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        settings,
        server_url="https://mcp.local/mcp",
    )

    app = FastAPI()
    app.include_router(plugin.root_router(SimpleNamespace()))

    with TestClient(app) as client:
        path_response = client.get("/.well-known/oauth-protected-resource/mcp")
        assert path_response.status_code == 200
        payload = path_response.json()
        assert payload["resource"] == "https://mcp.local/mcp"
        assert payload["authorization_servers"] == ["https://auth.local/oauth"]

        root_response = client.get("/.well-known/oauth-protected-resource")
        assert root_response.status_code == 200
        assert root_response.json() == payload
