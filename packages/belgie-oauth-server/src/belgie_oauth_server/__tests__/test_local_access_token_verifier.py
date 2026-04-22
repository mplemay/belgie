from urllib.parse import parse_qs, urlparse

import pytest
from belgie_oauth_server.__tests__.helpers import build_oauth_provider
from belgie_oauth_server.provider import AuthorizationParams
from belgie_oauth_server.utils import create_code_challenge
from belgie_oauth_server.verifier import verify_local_access_token

TEST_REDIRECT = "https://example.com/callback"


@pytest.mark.asyncio
async def test_verify_local_access_token_falls_back_to_stored_opaque_token() -> None:
    _settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=[TEST_REDIRECT],
        base_url="https://example.com",
    )

    token = await provider.issue_client_credentials_token("test-client", ["user"])
    verified = await verify_local_access_token(provider, token.access_token)

    assert verified is not None
    assert verified.source == "stored"
    assert verified.token.client_id == "test-client"


@pytest.mark.asyncio
async def test_verify_local_access_token_rejects_revoked_signed_token() -> None:
    settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=[TEST_REDIRECT],
        base_url="https://example.com",
        valid_audiences=["https://example.com/mcp"],
    )

    oauth_client = await provider.get_client("test-client")
    assert oauth_client is not None
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-jwt",
            scopes=["user"],
            code_challenge=create_code_challenge("verifier"),
            redirect_uri=TEST_REDIRECT,
            redirect_uri_provided_explicitly=True,
            resource=None,
            individual_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa",
            session_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb",
        ),
    )

    redirect_url = await provider.issue_authorization_code("state-jwt")
    code = parse_qs(urlparse(redirect_url).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)
    assert authorization_code is not None

    token = await provider.exchange_authorization_code(
        authorization_code,
        access_token_resource="https://example.com/mcp",
    )
    verified_before_revoke = await verify_local_access_token(
        provider,
        token.access_token,
        audience="https://example.com/mcp",
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
            audience="https://example.com/mcp",
        )
        is None
    )


@pytest.mark.asyncio
async def test_verify_local_access_token_preserves_reserved_claims_with_custom_claims() -> None:
    individual_id = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    session_id = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
    settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=[TEST_REDIRECT],
        base_url="https://example.com",
        valid_audiences=["https://example.com/mcp"],
        custom_access_token_claims=lambda payload: {
            "sub": "not-a-uuid",
            "scope": "admin",
            "aud": "https://example.com/other",
            "azp": "other-client",
            "sid": "override-session",
            "custom_claim": f"custom-{payload['client_id']}",
        },
    )

    oauth_client = await provider.get_client("test-client")
    assert oauth_client is not None
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-custom-claims",
            scopes=["user"],
            code_challenge=create_code_challenge("verifier"),
            redirect_uri=TEST_REDIRECT,
            redirect_uri_provided_explicitly=True,
            resource=None,
            individual_id=individual_id,
            session_id=session_id,
        ),
    )

    redirect_url = await provider.issue_authorization_code("state-custom-claims")
    code = parse_qs(urlparse(redirect_url).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)
    assert authorization_code is not None

    token = await provider.exchange_authorization_code(
        authorization_code,
        access_token_resource="https://example.com/mcp",
    )
    decoded = provider.signing_state.decode(
        token.access_token,
        audience="https://example.com/mcp",
        issuer=str(settings.issuer_url),
    )

    assert decoded["sub"] == individual_id
    assert decoded["scope"] == "user"
    assert decoded["aud"] == "https://example.com/mcp"
    assert decoded["azp"] == "test-client"
    assert decoded["sid"] == session_id
    assert decoded["custom_claim"] == "custom-test-client"

    verified = await verify_local_access_token(
        provider,
        token.access_token,
        audience="https://example.com/mcp",
    )

    assert verified is not None
    assert verified.source == "jwt"
    assert verified.token.client_id == "test-client"
    assert verified.token.scopes == ["user"]
    assert verified.token.resource == "https://example.com/mcp"
    assert verified.token.individual_id == individual_id
    assert verified.token.session_id == session_id
