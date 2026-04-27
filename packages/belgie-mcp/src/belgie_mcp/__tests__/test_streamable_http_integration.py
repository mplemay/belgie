from __future__ import annotations

import json
from dataclasses import dataclass
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

pytest.importorskip("mcp")
pytest.importorskip("belgie_oauth_server")

from belgie_core.core.settings import BelgieSettings
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.__tests__.test_oauth_plugin_integration import _build_app
from mcp.client.auth import OAuthClientProvider
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.server.auth.routes import build_resource_metadata_url
from mcp.server.mcpserver import MCPServer
from mcp.shared.auth import OAuthClientInformationFull, OAuthClientMetadata, OAuthToken

from belgie_mcp.auth_context import get_verified_access_token
from belgie_mcp.plugin import Mcp, McpPlugin

PUBLIC_TOKEN_ENDPOINT_AUTH_METHOD = "none"  # noqa: S105


def _belgie_settings() -> BelgieSettings:
    return BelgieSettings(secret="test-secret", base_url="https://example.com")


def _build_streamable_http_app(server_url: str) -> tuple[McpPlugin, TestClient]:
    oauth_settings = build_oauth_settings(
        base_url="https://auth.local",
        test_redirect_uris=["http://localhost/callback"],
        default_scopes=["user"],
    )
    plugin = McpPlugin(
        _belgie_settings(),
        Mcp(
            oauth=oauth_settings,
            server_url=server_url,
            required_scopes=["user"],
        ),
    )
    server = MCPServer(
        name="Belgie MCP",
        token_verifier=plugin.token_verifier,
        auth=plugin.auth,
    )
    return plugin, TestClient(server.streamable_http_app(streamable_http_path="/", host="testserver"))


def test_streamable_http_app_returns_www_authenticate_with_resource_metadata() -> None:
    plugin, client = _build_streamable_http_app("https://mcp.local/mcp")

    response = client.get("/")

    assert response.status_code == 401
    assert response.json() == {
        "error": "invalid_token",
        "error_description": "Authentication required",
    }
    assert response.headers["www-authenticate"] == (
        'Bearer error="invalid_token", error_description="Authentication required", '
        'resource_metadata="https://mcp.local/.well-known/oauth-protected-resource/mcp"'
    )
    assert str(plugin.auth.resource_server_url) == "https://mcp.local/mcp"


def test_streamable_http_app_exposes_protected_resource_metadata_route() -> None:
    plugin, client = _build_streamable_http_app("https://mcp.local/mcp")

    response = client.get("/.well-known/oauth-protected-resource/mcp")

    assert response.status_code == 200
    assert response.json() == {
        "resource": "https://mcp.local/mcp",
        "authorization_servers": ["https://auth.local/auth"],
        "scopes_supported": ["user"],
        "bearer_methods_supported": ["header"],
    }
    assert str(plugin.auth.issuer_url) == "https://auth.local/auth"


@dataclass
class _MemoryOAuthStorage:
    tokens: OAuthToken | None = None
    client_info: OAuthClientInformationFull | None = None

    async def get_tokens(self) -> OAuthToken | None:
        return self.tokens

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self.tokens = tokens

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        return self.client_info

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self.client_info = client_info


@pytest.mark.asyncio
async def test_streamable_http_client_completes_oauth_flow_and_reads_resource() -> None:
    server_url = "http://testserver/mcp/"
    oauth_settings = build_oauth_settings(
        base_url="http://testserver",
        test_redirect_uris=["http://localhost:6274/oauth/callback"],
        default_scopes=["user"],
        allow_dynamic_client_registration=True,
        allow_unauthenticated_client_registration=True,
        trusted_client_resolver=lambda _client: True,
        valid_audiences=[server_url],
    )
    app, oauth_plugin, belgie_client = _build_app(oauth_settings)
    plugin = McpPlugin(
        BelgieSettings(secret="test-secret", base_url="http://testserver"),
        Mcp(
            oauth=oauth_settings,
            server_url=server_url,
            required_scopes=["user"],
        ),
    )
    _ = plugin.router(SimpleNamespace(plugins=[oauth_plugin, plugin]))
    server = MCPServer(
        name="Belgie MCP",
        token_verifier=plugin.token_verifier,
        auth=plugin.auth,
    )

    @server.resource("resource://session")
    def session_resource() -> str:
        verified = get_verified_access_token()
        assert verified is not None
        return json.dumps(
            {
                "subject": verified.subject,
                "issuer": verified.issuer,
                "client_id": verified.token.client_id,
                "resource": verified.token.resource,
            },
        )

    metadata_path = urlparse(str(build_resource_metadata_url(plugin.auth.resource_server_url))).path

    @app.get(metadata_path)
    async def protected_resource_metadata() -> JSONResponse:
        metadata = plugin.protected_resource_metadata(scopes_supported=["user"])
        return JSONResponse(metadata.model_dump(mode="json", exclude_none=True))

    mcp_app = server.streamable_http_app(
        streamable_http_path="/",
        host="testserver",
        json_response=True,
        stateless_http=True,
    )
    app.mount(plugin.server_path, mcp_app)

    callback_result: tuple[str, str | None] | None = None
    browser_transport = httpx.ASGITransport(app=app)

    async def redirect_handler(url: str) -> None:
        nonlocal callback_result
        async with httpx.AsyncClient(transport=browser_transport, base_url="http://testserver") as browser:
            response = await browser.get(url, headers={"x-authenticated": "true"}, follow_redirects=False)
            while response.status_code in {302, 307, 308}:
                location = response.headers["location"]
                if location.startswith("http://localhost:6274/oauth/callback"):
                    query = parse_qs(urlparse(location).query)
                    callback_result = (query["code"][0], query.get("state", [None])[0])
                    return
                response = await browser.get(
                    location,
                    headers={"x-authenticated": "true"},
                    follow_redirects=False,
                )
        msg = f"authorization flow did not reach callback: {url}"
        raise AssertionError(msg)

    async def callback_handler() -> tuple[str, str | None]:
        assert callback_result is not None
        return callback_result

    storage = _MemoryOAuthStorage()
    auth = OAuthClientProvider(
        server_url,
        OAuthClientMetadata(
            redirect_uris=["http://localhost:6274/oauth/callback"],
            token_endpoint_auth_method="none",
            grant_types=["authorization_code"],
        ),
        storage,
        redirect_handler=redirect_handler,
        callback_handler=callback_handler,
    )

    async with (
        mcp_app.router.lifespan_context(mcp_app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            auth=auth,
        ) as http_client,
        streamable_http_client(server_url, http_client=http_client) as (read_stream, write_stream),
        ClientSession(read_stream=read_stream, write_stream=write_stream) as session,
    ):
        await session.initialize()
        resource = await session.read_resource("resource://session")

    assert storage.client_info is not None
    assert storage.client_info.token_endpoint_auth_method == PUBLIC_TOKEN_ENDPOINT_AUTH_METHOD
    assert storage.tokens is not None
    assert storage.tokens.access_token
    assert len(resource.contents) == 1

    content = resource.contents[0]
    payload = json.loads(content.text)
    assert payload == {
        "subject": str(belgie_client.user.id),
        "issuer": "http://testserver/auth",
        "client_id": storage.client_info.client_id,
        "resource": server_url,
    }
