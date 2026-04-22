from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import pytest
import respx
from belgie_oauth_server.__tests__.helpers import build_oauth_provider
from belgie_oauth_server.models import OAuthServerClientMetadata
from belgie_oauth_server.provider import (
    AccessToken as OAuthServerAccessToken,
    AuthorizationParams,
    SimpleOAuthProvider,
)
from belgie_oauth_server.resource_verifier import (
    RemoteIntrospectionConfig,
    verify_resource_access_token,
)
from belgie_oauth_server.utils import create_code_challenge
from httpx import Response
from pydantic import AnyUrl, SecretStr


@pytest.mark.asyncio
async def test_verify_resource_access_token_returns_local_token_and_subject() -> None:
    individual_id = str(uuid4())
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="https://issuer.local",
        valid_audiences=["https://issuer.local/mcp"],
    )
    token_value, stored_token, _client = await _issue_dynamic_client_access_token(
        provider,
        individual_id=individual_id,
        resource="https://issuer.local/mcp",
    )

    verified = await verify_resource_access_token(token_value, provider=provider)

    assert verified is not None
    assert verified.source == "jwt"
    assert verified.token.client_id == stored_token.client_id
    assert verified.token.scopes == stored_token.scopes
    assert verified.token.expires_at == stored_token.expires_at
    assert verified.token.resource == stored_token.resource
    assert verified.token.individual_id == stored_token.individual_id
    assert verified.token.session_id == stored_token.session_id
    assert verified.individual_id == individual_id
    assert verified.subject == individual_id
    assert verified.issuer == provider.issuer_url


@pytest.mark.asyncio
async def test_verify_resource_access_token_uses_public_sub_for_pairwise_clients() -> None:
    """Resource verification exposes JWT `sub` (public id) even when the client is pairwise.

    id_token and introspection use pairwise; access tokens follow better-auth's createJwtAccessToken.
    """
    individual_id = str(uuid4())
    settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="https://issuer.local",
        pairwise_secret=SecretStr("x" * 32),
        valid_audiences=["https://issuer.local/mcp"],
    )
    token_value, _stored_token, client = await _issue_dynamic_client_access_token(
        provider,
        individual_id=individual_id,
        resource="https://issuer.local/mcp",
        subject_type="pairwise",
    )

    verified = await verify_resource_access_token(token_value, provider=provider)
    assert verified is not None
    assert verified.individual_id == individual_id
    assert verified.subject == individual_id
    assert provider.resolve_subject_identifier(client, individual_id) != individual_id
    assert settings.pairwise_secret is not None


@respx.mock
@pytest.mark.asyncio
async def test_verify_resource_access_token_falls_back_to_introspection() -> None:
    endpoint = "https://issuer.local/introspect"
    route = respx.post(endpoint).mock(
        return_value=Response(
            200,
            json={
                "active": True,
                "client_id": "client",
                "scope": "user read",
                "exp": 123,
                "iat": 100,
                "aud": "https://mcp.local",
                "sub": str(uuid4()),
                "iss": "https://issuer.local/auth/oauth",
            },
        ),
    )

    verified = await verify_resource_access_token(
        "token",
        introspection=RemoteIntrospectionConfig(
            introspection_endpoint=endpoint,
            client_id="introspect-client",
            client_secret="introspect-secret",
        ),
    )

    assert verified is not None
    assert verified.source == "introspection"
    assert verified.token.client_id == "client"
    assert verified.token.scopes == ["user", "read"]
    assert verified.token.resource == "https://mcp.local"
    assert verified.individual_id is None
    assert verified.subject is not None
    assert verified.issuer == "https://issuer.local/auth/oauth"
    assert route.called is True
    assert route.calls[0].request.headers["Authorization"].startswith("Basic ")


@respx.mock
@pytest.mark.asyncio
async def test_verify_resource_access_token_rejects_invalid_local_resource_without_introspection_fallback() -> None:
    endpoint = "https://issuer.local/introspect"
    route = respx.post(endpoint).mock(
        return_value=Response(
            200,
            json={
                "active": True,
                "client_id": "client",
                "scope": "user",
                "exp": 123,
                "aud": "https://issuer.local/mcp",
            },
        ),
    )
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=["https://example.com/callback"],
        base_url="https://issuer.local",
        valid_audiences=["https://issuer.local/mcp"],
    )
    token_value, _stored_token, _client = await _issue_dynamic_client_access_token(
        provider,
        resource="https://issuer.local/mcp",
    )

    verified = await verify_resource_access_token(
        token_value,
        provider=provider,
        resource_validator=lambda resource: resource == "https://other.local/mcp",
        introspection=RemoteIntrospectionConfig(introspection_endpoint=endpoint),
    )

    assert verified is None
    assert route.called is False


async def _issue_dynamic_client_access_token(
    provider: SimpleOAuthProvider,
    *,
    individual_id: str | None = None,
    resource: str | None = None,
    subject_type: str | None = None,
) -> tuple[str, OAuthServerAccessToken, OAuthServerClientMetadata]:
    client = await provider.register_client(
        OAuthServerClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:6274/oauth/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="user",
            token_endpoint_auth_method="none",
            subject_type=subject_type,
        ),
    )
    state = await provider.authorize(
        client,
        AuthorizationParams(
            state=None,
            scopes=["user"],
            code_challenge=create_code_challenge("verifier"),
            redirect_uri=AnyUrl("http://localhost:6274/oauth/callback"),
            redirect_uri_provided_explicitly=True,
            resource=None,
            individual_id=individual_id,
            session_id=str(uuid4()),
        ),
    )
    redirect = await provider.issue_authorization_code(state)
    code = parse_qs(urlparse(redirect).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)
    assert authorization_code is not None
    token_response = await provider.exchange_authorization_code(
        authorization_code,
        access_token_resource=resource,
    )
    stored_token = await provider.load_access_token(token_response.access_token)
    assert stored_token is not None
    return token_response.access_token, stored_token, client
