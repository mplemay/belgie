from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

from belgie_core.core.settings import BelgieSettings
from belgie_mcp.plugin import Mcp, McpPlugin
from belgie_mcp.verifier import BelgieOAuthTokenVerifier
from belgie_oauth_server.settings import OAuthServer
from mcp.server.mcpserver import MCPServer


def _belgie_settings() -> BelgieSettings:
    return BelgieSettings(secret="test-secret", base_url="https://example.com")


def test_mcp_plugin_builds_auth_and_verifier() -> None:
    settings = OAuthServer(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        _belgie_settings(),
        Mcp(
            oauth=settings,
            server_url="https://mcp.local/mcp",
        ),
    )

    assert str(plugin.auth.issuer_url) == "https://auth.local/auth/oauth"
    assert str(plugin.auth.resource_server_url) == "https://mcp.local/mcp"
    assert isinstance(plugin.token_verifier, BelgieOAuthTokenVerifier)


def test_mcp_plugin_public_returns_none() -> None:
    settings = OAuthServer(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        _belgie_settings(),
        Mcp(
            oauth=settings,
            server_url="https://mcp.local/mcp",
        ),
    )

    assert plugin.public(SimpleNamespace()) is None


def test_mcp_plugin_builds_server_url_from_base_url() -> None:
    settings = OAuthServer(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        _belgie_settings(),
        Mcp(
            oauth=settings,
            base_url="https://example.com",
            server_path="/mcp",
        ),
    )

    assert str(plugin.auth.resource_server_url) == "https://example.com/mcp"


def test_mcp_plugin_defaults_base_url_from_belgie_settings() -> None:
    settings = OAuthServer(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )

    plugin = McpPlugin(
        _belgie_settings(),
        Mcp(
            oauth=settings,
            server_path="/mcp",
        ),
    )

    assert str(plugin.auth.resource_server_url) == "https://example.com/mcp"


def test_mount_streamable_http_accepts_alias_path_without_redirect() -> None:
    settings = OAuthServer(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )
    plugin = McpPlugin(
        _belgie_settings(),
        Mcp(
            oauth=settings,
            server_path="/mcp",
        ),
    )
    server = MCPServer(name="Belgie MCP")
    app = _build_test_app(plugin, server)

    with TestClient(app, base_url="http://localhost:8000") as client:
        alias_response = client.post(
            "/mcp",
            headers={"Content-Type": "application/json"},
            content="{}",
            follow_redirects=False,
        )
        mounted_response = client.post(
            "/mcp/",
            headers={"Content-Type": "application/json"},
            content="{}",
            follow_redirects=False,
        )

    assert alias_response.status_code == 400
    assert mounted_response.status_code == 400
    assert alias_response.headers.get("location") is None
    assert mounted_response.headers.get("location") is None
    assert alias_response.json() == mounted_response.json()


def test_mount_streamable_http_preserves_auth_middleware() -> None:
    settings = OAuthServer(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )
    plugin = McpPlugin(
        _belgie_settings(),
        Mcp(
            oauth=settings,
            server_path="/mcp",
        ),
    )
    verifier = _StubTokenVerifier()
    server = MCPServer(
        name="Belgie MCP",
        auth=plugin.auth,
        token_verifier=verifier,
    )
    app = _build_test_app(plugin, server)

    with TestClient(app, base_url="http://localhost:8000") as client:
        alias_response = client.post(
            "/mcp",
            headers={"Authorization": "Bearer alias-token"},
            follow_redirects=False,
        )
        mounted_response = client.post(
            "/mcp/",
            headers={"Authorization": "Bearer mounted-token"},
            follow_redirects=False,
        )

    assert verifier.tokens == ["alias-token", "mounted-token"]
    assert alias_response.status_code == 401
    assert mounted_response.status_code == 401
    assert alias_response.headers.get("location") is None
    assert mounted_response.headers.get("location") is None
    assert alias_response.json() == mounted_response.json()


def _build_test_app(plugin: McpPlugin, server: MCPServer) -> FastAPI:
    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        async with server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    _ = plugin.mount_streamable_http(app, server, host="localhost")
    return app


@dataclass(slots=True)
class _StubTokenVerifier:
    tokens: list[str] = field(default_factory=list)

    async def verify_token(self, token: str) -> None:
        self.tokens.append(token)
