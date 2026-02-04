import pytest
import respx
from httpx import Response

pytest.importorskip("mcp")
pytest.importorskip("belgie_oauth")

from belgie_mcp.verifier import BelgieOAuthTokenVerifier, mcp_auth, mcp_token_verifier
from belgie_oauth.settings import OAuthSettings
from belgie_oauth.utils import join_url
from mcp.server.mcpserver import MCPServer


@respx.mock
@pytest.mark.asyncio
async def test_verify_token_inactive_returns_none() -> None:
    endpoint = "https://issuer.local/introspect"
    respx.post(endpoint).mock(return_value=Response(200, json={"active": False}))

    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
    )

    assert await verifier.verify_token("token") is None


@respx.mock
@pytest.mark.asyncio
async def test_verify_token_non_200_returns_none() -> None:
    endpoint = "https://issuer.local/introspect"
    respx.post(endpoint).mock(return_value=Response(500))

    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
    )

    assert await verifier.verify_token("token") is None


@respx.mock
@pytest.mark.asyncio
async def test_verify_token_active_returns_access_token() -> None:
    endpoint = "https://issuer.local/introspect"
    respx.post(endpoint).mock(
        return_value=Response(
            200,
            json={
                "active": True,
                "client_id": "client",
                "scope": "user read",
                "exp": 123,
                "aud": "https://mcp.local",
            },
        ),
    )

    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
    )

    token = await verifier.verify_token("token")

    assert token is not None
    assert token.client_id == "client"
    assert token.scopes == ["user", "read"]
    assert token.expires_at == 123
    assert token.resource == "https://mcp.local"


@respx.mock
@pytest.mark.asyncio
async def test_verify_token_strict_resource_rejects_mismatch() -> None:
    endpoint = "https://issuer.local/introspect"
    respx.post(endpoint).mock(
        return_value=Response(
            200,
            json={
                "active": True,
                "client_id": "client",
                "scope": "user",
                "exp": 123,
                "aud": "https://other.local",
            },
        ),
    )

    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
        validate_resource=True,
    )

    assert await verifier.verify_token("token") is None


def test_mcp_auth_defaults() -> None:
    settings = OAuthSettings(
        base_url="https://issuer.local",
        redirect_uris=["https://app.local/callback"],
    )

    auth = mcp_auth(settings, server_url="https://mcp.local/mcp")

    assert str(auth.issuer_url) == "https://issuer.local/auth/oauth"
    assert str(auth.resource_server_url) == "https://mcp.local/mcp"
    assert auth.required_scopes == ["user"]


def test_mcp_auth_overrides() -> None:
    settings = OAuthSettings(
        base_url="https://issuer.local",
        redirect_uris=["https://app.local/callback"],
    )

    auth = mcp_auth(
        settings,
        server_url="https://mcp.local/mcp",
        required_scopes=["scope"],
    )

    assert auth.required_scopes == ["scope"]


def test_mcp_auth_requires_issuer_url() -> None:
    settings = OAuthSettings(redirect_uris=["https://app.local/callback"])

    with pytest.raises(ValueError, match="issuer_url"):
        mcp_auth(settings, server_url="https://mcp.local/mcp")


def test_mcp_token_verifier_defaults() -> None:
    settings = OAuthSettings(
        base_url="https://issuer.local",
        redirect_uris=["https://app.local/callback"],
    )

    verifier = mcp_token_verifier(settings, server_url="https://mcp.local/mcp")

    assert verifier.introspection_endpoint == join_url("https://issuer.local/auth/oauth", "introspect")


def test_mcp_token_verifier_overrides() -> None:
    settings = OAuthSettings(
        base_url="https://issuer.local",
        redirect_uris=["https://app.local/callback"],
    )

    verifier = mcp_token_verifier(
        settings,
        server_url="https://mcp.local/mcp",
        introspection_endpoint="https://custom.local/introspect",
    )

    assert verifier.introspection_endpoint == "https://custom.local/introspect"


def test_mcp_server_init_with_bundle() -> None:
    settings = OAuthSettings(
        base_url="https://issuer.local",
        redirect_uris=["https://app.local/callback"],
    )
    auth = mcp_auth(settings, server_url="https://mcp.local/mcp")
    token_verifier = mcp_token_verifier(settings, server_url="https://mcp.local/mcp")

    server = MCPServer(
        name="Test",
        token_verifier=token_verifier,
        auth=auth,
    )

    assert isinstance(server, MCPServer)
