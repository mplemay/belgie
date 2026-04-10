from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from belgie_core.core.belgie import Belgie
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.utils import create_code_challenge
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


def _authorize_params(
    oauth_settings: OAuthServer,
    *,
    state: str,
    prompt: str | None = None,
) -> dict[str, str]:
    params = {
        "response_type": "code",
        "client_id": oauth_settings.client_id,
        "redirect_uri": str(oauth_settings.redirect_uris[0]),
        "code_challenge": create_code_challenge("verifier"),
        "code_challenge_method": "S256",
        "state": state,
    }
    if prompt is not None:
        params["prompt"] = prompt
    return params


async def _create_login_state(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServer,
    *,
    state: str,
    prompt: str | None = None,
) -> str:
    authorize_response = await async_client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(oauth_settings, state=state, prompt=prompt),
        follow_redirects=False,
    )
    assert authorize_response.status_code == 302
    location = authorize_response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.path == "/auth/oauth/login"
    return query["state"][0]


@pytest.mark.asyncio
async def test_login_missing_state_returns_400(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/auth/oauth/login")

    assert response.status_code == 400
    assert response.json()["detail"] == "missing state"


@pytest.mark.asyncio
async def test_login_redirects_to_configured_login_url(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServer,
) -> None:
    state = await _create_login_state(async_client, oauth_settings, state="state-123")
    response = await async_client.get(
        "/auth/oauth/login",
        params={"state": state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert parsed.path == "/login/google"
    assert query["return_to"][0] == "http://testserver/auth/oauth/login/callback?state=state-123"
    assert query["intent"][0] == "login"


@pytest.mark.asyncio
async def test_login_redirects_to_signup_url_when_prompt_create(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServer,
) -> None:
    state = await _create_login_state(async_client, oauth_settings, state="state-create", prompt="create")
    response = await async_client.get(
        "/auth/oauth/login",
        params={"state": state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert parsed.path == "/signup"
    assert query["return_to"][0] == "http://testserver/auth/oauth/continue?state=state-create&created=true"
    assert query["intent"][0] == "create"


@pytest.mark.asyncio
async def test_login_redirects_to_configured_login_url_when_prompt_login(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServer,
) -> None:
    state = await _create_login_state(async_client, oauth_settings, state="state-login", prompt="login")
    response = await async_client.get(
        "/auth/oauth/login",
        params={"state": state},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert parsed.path == "/login/google"
    assert query["return_to"][0] == "http://testserver/auth/oauth/login/callback?state=state-login"
    assert query["intent"][0] == "login"


@pytest.mark.asyncio
async def test_authorize_rejects_prompt_with_select_account_when_not_configured(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServer,
) -> None:
    response = await async_client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(
            oauth_settings,
            state="state-create-multi",
            prompt="select_account create",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert parsed.path == "/callback"
    assert query["error"][0] == "invalid_request"
    assert query["error_description"][0] == "unsupported prompt type"
    assert query["state"][0] == "state-create-multi"
    assert query["iss"][0] == "http://testserver/auth/oauth"


@pytest.mark.asyncio
async def test_authorize_rejects_select_account_prompt_without_configured_page(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServer,
) -> None:
    response = await async_client.get(
        "/auth/oauth/authorize",
        params=_authorize_params(
            oauth_settings,
            state="state-unknown-prompt",
            prompt="select_account",
        ),
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert parsed.path == "/callback"
    assert query["error"][0] == "invalid_request"
    assert query["error_description"][0] == "unsupported prompt type"
    assert query["state"][0] == "state-unknown-prompt"
    assert query["iss"][0] == "http://testserver/auth/oauth"


@pytest.mark.asyncio
async def test_login_prompt_create_falls_back_to_login_url_when_signup_url_missing(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> None:
    settings = OAuthServer(
        base_url=oauth_settings.base_url,
        prefix=oauth_settings.prefix,
        login_url="/login/google",
        signup_url=None,
        client_id=oauth_settings.client_id,
        client_secret=SecretStr("test-secret"),
        redirect_uris=oauth_settings.redirect_uris,
        default_scope=oauth_settings.default_scope,
    )
    belgie_instance.add_plugin(settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        state = await _create_login_state(client, settings, state="state-fallback", prompt="create")
        response = await client.get(
            "/auth/oauth/login",
            params={"state": state},
            follow_redirects=False,
        )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert parsed.path == "/login/google"
    assert query["return_to"][0] == "http://testserver/auth/oauth/continue?state=state-fallback&created=true"
    assert query["intent"][0] == "create"


@pytest.mark.asyncio
async def test_login_callback_requires_session(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get(
        "/auth/oauth/login/callback",
        params={"state": "state-123"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "login_required"


@pytest.mark.asyncio
async def test_login_callback_rejects_invalid_state(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    create_individual_session,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "user@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    response = await async_client.get(
        "/auth/oauth/login/callback",
        params={"state": "bad-state"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid state parameter"
