import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

from belgie_mcp.plugin import BelgieMcpPlugin
from belgie_mcp.verifier import BelgieOAuthTokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer


def test_plugin_installs_prm_routes() -> None:
    auth = AuthSettings(
        issuer_url="https://auth.local/oauth",
        resource_server_url="https://mcp.local/mcp",
        required_scopes=["user"],
    )
    server = MCPServer(
        name="Test",
        token_verifier=BelgieOAuthTokenVerifier(
            introspection_endpoint="https://auth.local/oauth/introspect",
            server_url="https://mcp.local/mcp",
        ),
        auth=auth,
    )
    app = FastAPI()

    BelgieMcpPlugin(server=server, mount_path="/mcp").install(app)

    with TestClient(app) as client:
        path_response = client.get("/.well-known/oauth-protected-resource/mcp")
        assert path_response.status_code == 200
        payload = path_response.json()
        assert payload["resource"] == "https://mcp.local/mcp"
        assert payload["authorization_servers"] == ["https://auth.local/oauth"]

        root_response = client.get("/.well-known/oauth-protected-resource")
        assert root_response.status_code == 200
        assert root_response.json() == payload


def test_plugin_mounts_mcp_app() -> None:
    auth = AuthSettings(
        issuer_url="https://auth.local/oauth",
        resource_server_url="https://mcp.local/mcp",
        required_scopes=["user"],
    )
    server = MCPServer(
        name="Test",
        token_verifier=BelgieOAuthTokenVerifier(
            introspection_endpoint="https://auth.local/oauth/introspect",
            server_url="https://mcp.local/mcp",
        ),
        auth=auth,
    )
    app = FastAPI()

    BelgieMcpPlugin(server=server, mount_path="/mcp").install(app)

    assert any(getattr(route, "path", "") == "/mcp" for route in app.router.routes)
