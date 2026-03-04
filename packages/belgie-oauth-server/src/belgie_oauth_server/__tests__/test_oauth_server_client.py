from __future__ import annotations

from urllib.parse import urlencode

import pytest
from belgie_oauth_server.client import OAuthServerClient
from belgie_oauth_server.provider import AuthorizationParams, SimpleOAuthProvider
from belgie_oauth_server.settings import OAuthServer
from fastapi import HTTPException
from starlette.requests import Request


def _build_request(query: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/login",
            "query_string": urlencode(query).encode("utf-8"),
            "headers": [],
        },
    )


@pytest.mark.asyncio
async def test_resolve_login_context_returns_state_intent_prompt_and_return_to() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    oauth_client = await provider.get_client(settings.client_id)
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-123",
            scopes=["user"],
            code_challenge="challenge",
            redirect_uri=settings.redirect_uris[0],
            redirect_uri_provided_explicitly=True,
            prompt="create",
            intent="create",
        ),
    )

    client = OAuthServerClient(provider=provider, issuer_url=str(settings.issuer_url))
    context = await client.resolve_login_context(_build_request({"state": "state-123"}))

    assert context.state == "state-123"
    assert context.intent == "create"
    assert context.prompt == "create"
    assert context.return_to == "http://example.com/auth/oauth/login/callback?state=state-123"


@pytest.mark.asyncio
async def test_resolve_login_context_extracts_state_from_return_to_query() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    oauth_client = await provider.get_client(settings.client_id)
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state="state-123",
            scopes=["user"],
            code_challenge="challenge",
            redirect_uri=settings.redirect_uris[0],
            redirect_uri_provided_explicitly=True,
        ),
    )

    client = OAuthServerClient(provider=provider, issuer_url=str(settings.issuer_url))
    context = await client.resolve_login_context(
        _build_request({"return_to": "http://example.com/auth/oauth/login/callback?state=state-123"}),
    )

    assert context.state == "state-123"
    assert context.intent == "login"
    assert context.prompt is None
    assert context.return_to == "http://example.com/auth/oauth/login/callback?state=state-123"


@pytest.mark.asyncio
async def test_resolve_login_context_rejects_missing_state() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    client = OAuthServerClient(provider=provider, issuer_url=str(settings.issuer_url))

    with pytest.raises(HTTPException) as exc:
        await client.resolve_login_context(_build_request({}))

    assert exc.value.status_code == 400
    assert exc.value.detail == "missing state"


@pytest.mark.asyncio
async def test_resolve_login_context_rejects_invalid_state() -> None:
    settings = OAuthServer(
        redirect_uris=["http://example.com/callback"],
        base_url="http://example.com",
        client_id="test-client",
    )
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url))
    client = OAuthServerClient(provider=provider, issuer_url=str(settings.issuer_url))

    with pytest.raises(HTTPException) as exc:
        await client.resolve_login_context(_build_request({"state": "invalid"}))

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid state parameter"
