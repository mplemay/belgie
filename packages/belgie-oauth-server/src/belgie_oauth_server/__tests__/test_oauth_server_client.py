from __future__ import annotations

from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode

import pytest
from belgie_oauth_server.__tests__.helpers import build_oauth_provider
from belgie_oauth_server.client import OAuthServerClient
from belgie_oauth_server.provider import AuthorizationParams, SimpleOAuthProvider
from fastapi import HTTPException
from starlette.requests import Request

if TYPE_CHECKING:
    from belgie_oauth_server.settings import OAuthServer

type OAuthIntent = Literal["login", "create", "consent", "select_account"]


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


TEST_REDIRECT = "https://example.com/callback"


async def _build_client() -> tuple[OAuthServerClient, SimpleOAuthProvider, OAuthServer]:
    settings, provider, _adapter, _db = build_oauth_provider(
        test_redirect_uris=[TEST_REDIRECT],
        base_url="https://example.com",
    )
    return OAuthServerClient(provider=provider, issuer_url=str(settings.issuer_url)), provider, settings


async def _store_state(
    provider: SimpleOAuthProvider,
    settings: OAuthServer,
    *,
    state: str,
    prompt: str | None = None,
    intent: OAuthIntent = "login",
) -> None:
    oauth_client = await provider.get_client("test-client")
    assert oauth_client is not None
    await provider.authorize(
        oauth_client,
        AuthorizationParams(
            state=state,
            scopes=["user"],
            code_challenge="challenge",
            redirect_uri=TEST_REDIRECT,
            redirect_uri_provided_explicitly=True,
            prompt=prompt,
            intent=intent,
        ),
    )


@pytest.mark.asyncio
async def test_try_resolve_login_context_returns_state_intent_prompt_and_return_to() -> None:
    client, provider, settings = await _build_client()
    await _store_state(provider, settings, state="state-123", prompt="create", intent="create")

    context = await client.try_resolve_login_context(_build_request({"state": "state-123"}))

    assert context is not None
    assert context.state == "state-123"
    assert context.intent == "create"
    assert context.prompt == "create"
    assert context.return_to == "https://example.com/auth/oauth2/continue?state=state-123&created=true"


@pytest.mark.asyncio
async def test_try_resolve_login_context_returns_consent_return_to() -> None:
    client, provider, settings = await _build_client()
    await _store_state(provider, settings, state="state-123", prompt="consent", intent="consent")

    context = await client.try_resolve_login_context(_build_request({"state": "state-123"}))

    assert context is not None
    assert context.intent == "consent"
    assert context.prompt == "consent"
    assert context.return_to == "https://example.com/auth/oauth2/consent?state=state-123"


@pytest.mark.asyncio
async def test_try_resolve_login_context_returns_select_account_return_to() -> None:
    client, provider, settings = await _build_client()
    await _store_state(
        provider,
        settings,
        state="state-123",
        prompt="select_account",
        intent="select_account",
    )

    context = await client.try_resolve_login_context(_build_request({"state": "state-123"}))

    assert context is not None
    assert context.intent == "select_account"
    assert context.prompt == "select_account"
    assert context.return_to == "https://example.com/auth/oauth2/continue?state=state-123&selected=true"


@pytest.mark.asyncio
async def test_try_resolve_login_context_extracts_state_from_return_to_query() -> None:
    client, provider, settings = await _build_client()
    await _store_state(provider, settings, state="state-123")

    context = await client.try_resolve_login_context(
        _build_request({"return_to": "https://example.com/auth/oauth2/login/callback?state=state-123"}),
    )

    assert context is not None
    assert context.state == "state-123"
    assert context.intent == "login"
    assert context.prompt is None
    assert context.return_to == "https://example.com/auth/oauth2/login/callback?state=state-123"


@pytest.mark.asyncio
async def test_try_resolve_login_context_returns_none_when_state_missing() -> None:
    client, _provider, _settings = await _build_client()

    context = await client.try_resolve_login_context(_build_request({}))

    assert context is None


@pytest.mark.asyncio
async def test_try_resolve_login_context_rejects_invalid_state() -> None:
    client, _provider, _settings = await _build_client()

    with pytest.raises(HTTPException) as exc:
        await client.try_resolve_login_context(_build_request({"state": "invalid"}))

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid state parameter"


@pytest.mark.asyncio
async def test_resolve_login_context_rejects_missing_state() -> None:
    client, _provider, _settings = await _build_client()

    with pytest.raises(HTTPException) as exc:
        await client.resolve_login_context(_build_request({}))

    assert exc.value.status_code == 400
    assert exc.value.detail == "missing state"


@pytest.mark.asyncio
async def test_resolve_login_context_rejects_invalid_state() -> None:
    client, _provider, _settings = await _build_client()

    with pytest.raises(HTTPException) as exc:
        await client.resolve_login_context(_build_request({"state": "invalid"}))

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid state parameter"


@pytest.mark.asyncio
async def test_try_resolve_login_context_prefers_explicit_state_over_return_to_state() -> None:
    client, provider, settings = await _build_client()
    await _store_state(provider, settings, state="valid-state")

    with pytest.raises(HTTPException) as exc:
        await client.try_resolve_login_context(
            _build_request(
                {
                    "state": "invalid-state",
                    "return_to": "https://example.com/auth/oauth2/login/callback?state=valid-state",
                },
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "Invalid state parameter"
