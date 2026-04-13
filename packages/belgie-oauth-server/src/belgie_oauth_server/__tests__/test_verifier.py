from urllib.parse import parse_qs, urlparse

import pytest
from belgie_oauth_server.__tests__.helpers import build_oauth_provider
from belgie_oauth_server.provider import AuthorizationParams
from belgie_oauth_server.settings import OAuthServerResource
from belgie_oauth_server.utils import create_code_challenge
from belgie_oauth_server.verifier import verify_local_access_token


@pytest.mark.asyncio
async def test_verify_local_access_token_falls_back_to_stored_opaque_token() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )

    token = await provider.issue_client_credentials_token("test-client", ["user"])
    verified = await verify_local_access_token(provider, token.access_token)

    assert verified is not None
    assert verified.source == "stored"
    assert verified.token.client_id == "test-client"


@pytest.mark.asyncio
async def test_verify_local_access_token_rejects_revoked_signed_token() -> None:
    settings, provider, _adapter, _db = build_oauth_provider(
        redirect_uris=["https://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
        resources=[OAuthServerResource(prefix="/mcp", scopes=["user"])],
    )

    oauth_client = await provider.get_client("test-client")
    assert oauth_client is not None
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-jwt",
            scopes=["user"],
            code_challenge=create_code_challenge("verifier"),
            redirect_uri=settings.redirect_uris[0],
            redirect_uri_provided_explicitly=True,
            resource="http://example.com/mcp",
            individual_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            session_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        ),
    )

    redirect_url = await provider.issue_authorization_code("state-jwt")
    code = parse_qs(urlparse(redirect_url).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)
    assert authorization_code is not None

    token = await provider.exchange_authorization_code(authorization_code)
    verified_before_revoke = await verify_local_access_token(
        provider,
        token.access_token,
        audience="http://example.com/mcp",
    )
    assert verified_before_revoke is not None
    assert verified_before_revoke.source == "jwt"

    stored_token = await provider.load_access_token(token.access_token)
    assert stored_token is not None
    await provider.revoke_token(stored_token)

    assert (
        await verify_local_access_token(
            provider,
            token.access_token,
            audience="http://example.com/mcp",
        )
        is None
    )
