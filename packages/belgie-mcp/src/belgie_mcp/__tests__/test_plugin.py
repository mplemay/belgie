from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import AnyUrl

pytest.importorskip("mcp")

from belgie_core.core.settings import BelgieSettings
from belgie_mcp.plugin import Mcp, McpPlugin
from belgie_mcp.verifier import BelgieOAuthTokenVerifier
from belgie_oauth_server.models import OAuthClientMetadata
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.provider import AccessToken as OAuthAccessToken, AuthorizationParams, SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServer
from mcp.server.auth.provider import AccessToken
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


@pytest.mark.asyncio
async def test_mcp_plugin_verifier_uses_linked_oauth_plugin_provider() -> None:
    settings = OAuthServer(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    oauth_plugin = OAuthServerPlugin(_belgie_settings(), settings)
    oauth_plugin._provider = provider
    plugin = McpPlugin(
        _belgie_settings(),
        Mcp(
            oauth=settings,
            server_url="https://mcp.local/mcp",
        ),
    )
    _ = plugin.router(SimpleNamespace(plugins=[oauth_plugin, plugin]))
    token_value, stored_token = await _issue_dynamic_client_access_token(
        provider,
        user_id=str(uuid4()),
        resource="https://mcp.local/mcp",
    )

    token = await plugin.token_verifier.verify_token(token_value)

    assert token == AccessToken(
        token=token_value,
        client_id=stored_token.client_id,
        scopes=["user"],
        expires_at=stored_token.expires_at,
        resource="https://mcp.local/mcp",
    )


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

    with TestClient(app, base_url="https://example.com") as client:
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


@pytest.mark.parametrize("host_header", ["localhost:8000", "127.0.0.1:8000", "[::1]:8000"])
def test_mount_streamable_http_allows_loopback_hosts(host_header: str) -> None:
    plugin = _build_plugin(server_url="http://localhost:8000/mcp")
    server = MCPServer(
        name="Belgie MCP",
        auth=plugin.auth,
        token_verifier=_AllowingTokenVerifier(),
    )
    app = _build_test_app(plugin, server)

    with TestClient(app, base_url="http://localhost:8000") as client:
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer valid-token",
                "Host": host_header,
            },
            json=_build_initialize_request(),
            follow_redirects=False,
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers.get("mcp-session-id")


def test_mount_streamable_http_allows_configured_external_host() -> None:
    plugin = _build_plugin(server_url="https://example.com/mcp")
    server = MCPServer(
        name="Belgie MCP",
        auth=plugin.auth,
        token_verifier=_AllowingTokenVerifier(),
    )
    app = _build_test_app(plugin, server)

    with TestClient(app, base_url="https://example.com") as client:
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer valid-token",
                "Host": "example.com",
            },
            json=_build_initialize_request(),
            follow_redirects=False,
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers.get("mcp-session-id")


def test_mount_streamable_http_rejects_mismatched_host() -> None:
    plugin = _build_plugin(server_url="http://localhost:8000/mcp")
    server = MCPServer(
        name="Belgie MCP",
        auth=plugin.auth,
        token_verifier=_AllowingTokenVerifier(),
    )
    app = _build_test_app(plugin, server)

    with TestClient(app, base_url="http://localhost:8000") as client:
        response = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer valid-token",
                "Host": "example.com",
            },
            json=_build_initialize_request(),
            follow_redirects=False,
        )

    assert response.status_code == 421
    assert response.text == "Invalid Host header"


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

    with TestClient(app, base_url="https://example.com") as client:
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
    _ = plugin.mount_streamable_http(app, server)
    return app


@dataclass(slots=True)
class _StubTokenVerifier:
    tokens: list[str] = field(default_factory=list)

    async def verify_token(self, token: str) -> None:
        self.tokens.append(token)


@dataclass(slots=True)
class _AllowingTokenVerifier:
    async def verify_token(self, token: str) -> AccessToken:
        return AccessToken(
            token=token,
            client_id="client",
            scopes=["user"],
        )


def _build_plugin(*, server_url: str) -> McpPlugin:
    settings = OAuthServer(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )
    return McpPlugin(
        _belgie_settings(),
        Mcp(
            oauth=settings,
            server_url=server_url,
        ),
    )


def _build_initialize_request() -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "test-client", "version": "1"},
        },
    }


async def _issue_dynamic_client_access_token(
    provider: SimpleOAuthProvider,
    *,
    user_id: str | None = None,
    resource: str | None = None,
) -> tuple[str, OAuthAccessToken]:
    client = await provider.register_client(
        OAuthClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:6274/oauth/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="user",
            token_endpoint_auth_method="none",
        ),
    )
    state = await provider.authorize(
        client,
        AuthorizationParams(
            state=None,
            scopes=["user"],
            code_challenge="test-challenge",
            redirect_uri=AnyUrl("http://localhost:6274/oauth/callback"),
            redirect_uri_provided_explicitly=True,
            resource=resource,
            user_id=user_id,
            session_id=str(uuid4()),
        ),
    )
    redirect = await provider.issue_authorization_code(state)
    code = parse_qs(urlparse(redirect).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)
    assert authorization_code is not None
    token_response = await provider.exchange_authorization_code(authorization_code)
    stored_token = await provider.load_access_token(token_response.access_token)
    assert stored_token is not None
    return token_response.access_token, stored_token
