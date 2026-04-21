from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import respx
from httpx import Response
from pydantic import AnyUrl

pytest.importorskip("mcp")
pytest.importorskip("belgie_oauth_server")

from belgie_mcp.verifier import BelgieOAuthTokenVerifier, mcp_auth, mcp_token_verifier
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.models import OAuthServerClientMetadata
from belgie_oauth_server.provider import AccessToken as OAuthServerAccessToken, AuthorizationParams, SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.testing import InMemoryDBConnection
from belgie_oauth_server.utils import join_url
from mcp.server.auth.provider import AccessToken
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


@pytest.mark.asyncio
async def test_verify_token_remote_jwks_accepts_resource_bound_signed_token() -> None:
    settings = _oauth_settings()
    provider = _build_provider(settings)
    token_value, stored_token = await _issue_dynamic_client_access_token(
        provider,
        individual_id=str(uuid4()),
        resource="https://mcp.local/mcp",
    )
    issuer_url = str(settings.issuer_url)
    endpoint = join_url(issuer_url, "introspect")
    jwks_endpoint = join_url(issuer_url, "jwks")
    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
        jwt_issuer=issuer_url,
        jwks_endpoint=jwks_endpoint,
    )
    with respx.mock(assert_all_called=False) as router:
        jwks_route = router.get(jwks_endpoint).mock(return_value=Response(200, json=provider.signing_state.jwks))
        introspection_route = router.post(endpoint).mock(return_value=Response(500))
        token = await verifier.verify_token(token_value)

    assert stored_token.client_id != settings.client_id
    assert token == AccessToken(
        token=token_value,
        client_id=stored_token.client_id,
        scopes=["user"],
        expires_at=stored_token.expires_at,
        resource="https://mcp.local/mcp",
    )
    assert jwks_route.called is True
    assert introspection_route.called is False


@pytest.mark.asyncio
async def test_verify_token_remote_jwks_falls_back_to_introspection_for_opaque_tokens() -> None:
    settings = _oauth_settings()
    provider = _build_provider(settings)
    token_value, _stored_token = await _issue_dynamic_client_access_token(
        provider,
        individual_id=str(uuid4()),
    )
    issuer_url = str(settings.issuer_url)
    endpoint = join_url(issuer_url, "introspect")
    jwks_endpoint = join_url(issuer_url, "jwks")
    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
        jwt_issuer=issuer_url,
        jwks_endpoint=jwks_endpoint,
    )
    with respx.mock(assert_all_called=False) as router:
        jwks_route = router.get(jwks_endpoint).mock(return_value=Response(200, json=provider.signing_state.jwks))
        introspection_route = router.post(endpoint).mock(
            return_value=Response(
                200,
                json={
                    "active": True,
                    "client_id": "client",
                    "scope": "user",
                    "exp": 123,
                    "aud": "https://mcp.local",
                },
            ),
        )
        token = await verifier.verify_token(token_value)

    assert token == AccessToken(
        token=token_value,
        client_id="client",
        scopes=["user"],
        expires_at=123,
        resource="https://mcp.local",
    )
    assert jwks_route.called is False
    assert introspection_route.called is True


@pytest.mark.asyncio
async def test_verify_token_remote_jwks_strict_resource_rejects_without_introspection() -> None:
    settings = _oauth_settings()
    provider = _build_provider(settings)
    token_value, _stored_token = await _issue_dynamic_client_access_token(
        provider,
        resource="https://other.local/mcp",
    )
    issuer_url = str(settings.issuer_url)
    endpoint = join_url(issuer_url, "introspect")
    jwks_endpoint = join_url(issuer_url, "jwks")
    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
        validate_resource=True,
        jwt_issuer=issuer_url,
        jwks_endpoint=jwks_endpoint,
    )
    with respx.mock(assert_all_called=False) as router:
        jwks_route = router.get(jwks_endpoint).mock(return_value=Response(200, json=provider.signing_state.jwks))
        introspection_route = router.post(endpoint).mock(return_value=Response(500))
        assert await verifier.verify_token(token_value) is None

    assert jwks_route.called is True
    assert introspection_route.called is False


@respx.mock
@pytest.mark.asyncio
async def test_verify_token_local_provider_accepts_dynamic_client_access_tokens() -> None:
    endpoint = "https://issuer.local/introspect"
    route = respx.post(endpoint).mock(return_value=Response(500))
    settings = _oauth_settings()
    provider = _build_provider(settings)
    token_value, stored_token = await _issue_dynamic_client_access_token(
        provider,
        individual_id=str(uuid4()),
        resource="https://mcp.local/mcp",
    )

    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
        provider_resolver=lambda: provider,
    )

    token = await verifier.verify_token(token_value)

    assert stored_token.client_id != settings.client_id
    assert token == AccessToken(
        token=token_value,
        client_id=stored_token.client_id,
        scopes=["user"],
        expires_at=stored_token.expires_at,
        resource="https://mcp.local/mcp",
    )
    assert route.called is False


@respx.mock
@pytest.mark.asyncio
async def test_verify_token_local_provider_rejects_revoked_signed_tokens() -> None:
    endpoint = "https://issuer.local/introspect"
    route = respx.post(endpoint).mock(return_value=Response(200, json={"active": False}))
    provider = _build_provider(_oauth_settings())
    token_value, stored_token = await _issue_dynamic_client_access_token(
        provider,
        individual_id=str(uuid4()),
        resource="https://mcp.local/mcp",
    )
    await provider.revoke_token(stored_token)
    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
        provider_resolver=lambda: provider,
    )

    assert await verifier.verify_token(token_value) is None
    assert route.called is True


@respx.mock
@pytest.mark.asyncio
async def test_verify_token_local_provider_falls_back_to_introspection_for_missing_tokens() -> None:
    endpoint = "https://issuer.local/introspect"
    route = respx.post(endpoint).mock(
        return_value=Response(
            200,
            json={
                "active": True,
                "client_id": "client",
                "scope": "user",
                "exp": 123,
                "aud": "https://mcp.local",
            },
        ),
    )
    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
        provider_resolver=lambda: _build_provider(_oauth_settings()),
    )

    token = await verifier.verify_token("missing-token")

    assert token == AccessToken(
        token="missing-token",
        client_id="client",
        scopes=["user"],
        expires_at=123,
        resource="https://mcp.local",
    )
    assert route.called is True


@respx.mock
@pytest.mark.asyncio
async def test_verify_token_local_provider_returns_none_for_expired_tokens() -> None:
    endpoint = "https://issuer.local/introspect"
    route = respx.post(endpoint).mock(return_value=Response(200, json={"active": False}))
    provider = _build_provider(_oauth_settings())
    token_value, _stored_token = await _issue_dynamic_client_access_token(provider)
    provider.adapter.access_tokens[provider._hash_value(token_value)].expires_at = datetime.fromtimestamp(0, UTC)
    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
        provider_resolver=lambda: provider,
    )

    assert await verifier.verify_token(token_value) is None
    assert provider._hash_value(token_value) not in provider.adapter.access_tokens
    assert route.called is True


@respx.mock
@pytest.mark.asyncio
async def test_verify_token_local_provider_strict_resource_rejects_mismatch() -> None:
    endpoint = "https://issuer.local/introspect"
    route = respx.post(endpoint).mock(return_value=Response(500))
    provider = _build_provider(_oauth_settings())
    token_value, _stored_token = await _issue_dynamic_client_access_token(
        provider,
        resource="https://other.local/mcp",
    )
    verifier = BelgieOAuthTokenVerifier(
        introspection_endpoint=endpoint,
        server_url="https://mcp.local/mcp",
        provider_resolver=lambda: provider,
        validate_resource=True,
    )

    assert await verifier.verify_token(token_value) is None
    assert route.called is False


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
    settings = build_oauth_settings(
        base_url="https://issuer.local",
        redirect_uris=["https://app.local/callback"],
    )

    auth = mcp_auth(settings, server_url="https://mcp.local/mcp")

    assert str(auth.issuer_url) == "https://issuer.local/auth/oauth"
    assert str(auth.resource_server_url) == "https://mcp.local/mcp"
    assert auth.required_scopes == []


def test_mcp_auth_uses_configured_default_scopes() -> None:
    settings = build_oauth_settings(
        base_url="https://issuer.local",
        redirect_uris=["https://app.local/callback"],
        default_scopes=["user", "profile"],
    )

    auth = mcp_auth(settings, server_url="https://mcp.local/mcp")

    assert auth.required_scopes == ["user", "profile"]


def test_mcp_auth_overrides() -> None:
    settings = build_oauth_settings(
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
    settings = build_oauth_settings(redirect_uris=["https://app.local/callback"], base_url=None)

    with pytest.raises(ValueError, match="issuer_url"):
        mcp_auth(settings, server_url="https://mcp.local/mcp")


def test_mcp_token_verifier_defaults() -> None:
    settings = build_oauth_settings(
        base_url="https://issuer.local",
        redirect_uris=["https://app.local/callback"],
    )

    verifier = mcp_token_verifier(settings, server_url="https://mcp.local/mcp")

    assert verifier.introspection_endpoint == join_url("https://issuer.local/auth/oauth", "introspect")
    assert verifier.jwks_endpoint == join_url("https://issuer.local/auth/oauth", "jwks")


def test_mcp_token_verifier_overrides() -> None:
    settings = build_oauth_settings(
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
    settings = build_oauth_settings(
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


def _oauth_settings() -> OAuthServer:
    return build_oauth_settings(
        base_url="https://issuer.local",
        redirect_uris=["http://localhost:6274/oauth/callback"],
        client_id="test-client",
        client_secret="test-secret",
        default_scopes=["user"],
    )


def _build_provider(settings: OAuthServer) -> SimpleOAuthProvider:
    db = InMemoryDBConnection()
    return SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url), database_factory=lambda: db)


async def _issue_dynamic_client_access_token(
    provider: SimpleOAuthProvider,
    *,
    individual_id: str | None = None,
    resource: str | None = None,
) -> tuple[str, OAuthServerAccessToken]:
    client = await provider.register_client(
        OAuthServerClientMetadata(
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
