from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from belgie_core.core.belgie import Belgie
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.settings import OAuthServerSettings
from belgie_oauth_server.utils import create_code_challenge
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_user_session(belgie: Belgie, db_session: AsyncSession, email: str) -> str:
    user = await belgie.adapter.create_user(db_session, email=email)
    session = await belgie.session_manager.create_session(db_session, user_id=user.id)
    return str(session.id)


def _authorize_params(
    oauth_settings: OAuthServerSettings,
    code_challenge: str,
    state: str | None = None,
    resource: str | None = None,
) -> dict[str, str]:
    params = {
        "response_type": "code",
        "client_id": oauth_settings.client_id,
        "redirect_uri": str(oauth_settings.redirect_uris[0]),
        "code_challenge": code_challenge,
        "state": state or "state-123",
    }
    if resource is not None:
        params["resource"] = resource
    return params


@pytest.mark.asyncio
async def test_authorize_redirects_to_login_when_unauthenticated(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServerSettings,
) -> None:
    verifier = "verifier"
    params = _authorize_params(oauth_settings, create_code_challenge(verifier))
    response = await async_client.get("/auth/oauth/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert parsed.path == "/auth/oauth/login"
    assert query["state"][0] == "state-123"


@pytest.mark.asyncio
async def test_authorize_returns_401_without_login_url(
    belgie_instance: Belgie,
    oauth_settings: OAuthServerSettings,
) -> None:
    settings = OAuthServerSettings(
        base_url=oauth_settings.base_url,
        prefix=oauth_settings.prefix,
        client_id=oauth_settings.client_id,
        client_secret=SecretStr("test-secret"),
        redirect_uris=oauth_settings.redirect_uris,
        default_scope=oauth_settings.default_scope,
        login_url=None,
    )
    belgie_instance.add_plugin(OAuthServerPlugin, settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        verifier = "verifier"
        params = _authorize_params(settings, create_code_challenge(verifier))
        response = await client.get("/auth/oauth/authorize", params=params, follow_redirects=False)

    assert response.status_code == 401
    assert response.json()["detail"] == "login_required"


@pytest.mark.asyncio
async def test_authorize_issues_code_without_login_url_when_authenticated(
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServerSettings,
) -> None:
    settings = OAuthServerSettings(
        base_url=oauth_settings.base_url,
        prefix=oauth_settings.prefix,
        client_id=oauth_settings.client_id,
        client_secret=SecretStr("test-secret"),
        redirect_uris=oauth_settings.redirect_uris,
        default_scope=oauth_settings.default_scope,
        login_url=None,
    )
    belgie_instance.add_plugin(OAuthServerPlugin, settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = await _create_user_session(belgie_instance, db_session, "user@test.com")
        client.cookies.set(belgie_instance.settings.cookie.name, session_id)

        params = _authorize_params(settings, create_code_challenge("verifier"), state="state-auth")
        response = await client.get("/auth/oauth/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert query["state"][0] == "state-auth"
    assert "code" in query


@pytest.mark.asyncio
async def test_authorize_issues_code_when_authenticated(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServerSettings,
) -> None:
    session_id = await _create_user_session(belgie_instance, db_session, "user@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    params = _authorize_params(oauth_settings, create_code_challenge("verifier"), state="state-auth")
    response = await async_client.get("/auth/oauth/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert query["state"][0] == "state-auth"
    assert "code" in query


@pytest.mark.asyncio
async def test_authorize_rejects_unknown_resource(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServerSettings,
) -> None:
    params = _authorize_params(
        oauth_settings,
        create_code_challenge("verifier"),
        resource="http://testserver/unknown-resource",
    )
    response = await async_client.get("/auth/oauth/authorize", params=params, follow_redirects=False)

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_target"


@pytest.mark.asyncio
async def test_authorize_accepts_configured_resource_when_authenticated(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServerSettings,
) -> None:
    session_id = await _create_user_session(belgie_instance, db_session, "user@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    params = _authorize_params(
        oauth_settings,
        create_code_challenge("verifier"),
        state="state-with-resource",
        resource="http://testserver/mcp",
    )
    response = await async_client.get("/auth/oauth/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert query["state"][0] == "state-with-resource"
    assert "code" in query
