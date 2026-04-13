from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
from pydantic import AnyUrl

pytest.importorskip("mcp")

from belgie_core.core.settings import BelgieSettings
from belgie_mcp.plugin import Mcp, McpPlugin
from belgie_mcp.verifier import BelgieOAuthTokenVerifier
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.models import OAuthClientMetadata
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.provider import AccessToken as OAuthAccessToken, AuthorizationParams, SimpleOAuthProvider
from belgie_oauth_server.testing import InMemoryDBConnection
from mcp.server.auth.provider import AccessToken


def _belgie_settings() -> BelgieSettings:
    return BelgieSettings(secret="test-secret", base_url="https://example.com")


def test_mcp_plugin_builds_auth_and_verifier() -> None:
    settings = build_oauth_settings(
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
    settings = build_oauth_settings(
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
    settings = build_oauth_settings(
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


def test_mcp_plugin_preserves_trailing_slash_in_server_path() -> None:
    settings = build_oauth_settings(
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
            server_path="/mcp/",
        ),
    )

    assert plugin.server_path == "/mcp/"
    assert str(plugin.auth.resource_server_url) == "https://example.com/mcp/"


def test_mcp_plugin_defaults_base_url_from_belgie_settings() -> None:
    settings = build_oauth_settings(
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


def test_mcp_plugin_preserves_trailing_slash_in_server_url() -> None:
    settings = build_oauth_settings(
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
            server_url="https://mcp.local/mcp/",
        ),
    )

    assert plugin.server_path == "/mcp/"
    assert str(plugin.auth.resource_server_url) == "https://mcp.local/mcp/"


@pytest.mark.asyncio
async def test_mcp_plugin_verifier_uses_linked_oauth_plugin_provider() -> None:
    settings = build_oauth_settings(
        base_url="https://auth.local",
        redirect_uris=["http://localhost/callback"],
        client_id="client",
        client_secret="secret",
        default_scope="user",
    )
    db = InMemoryDBConnection()
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url), database_factory=lambda: db)
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
        individual_id=str(uuid4()),
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


async def _issue_dynamic_client_access_token(
    provider: SimpleOAuthProvider,
    *,
    individual_id: str | None = None,
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
            individual_id=individual_id,
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
