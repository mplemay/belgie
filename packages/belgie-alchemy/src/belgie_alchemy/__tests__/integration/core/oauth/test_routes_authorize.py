from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from belgie_core.core.belgie import Belgie
from belgie_oauth_server.models import OAuthServerClientMetadata
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.utils import create_code_challenge
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


def _authorize_params(
    oauth_settings: OAuthServer,
    code_challenge: str,
    state: str | None = None,
    resource: str | None = None,
) -> dict[str, str]:
    params = {
        "response_type": "code",
        "client_id": oauth_settings.client_id,
        "redirect_uri": str(oauth_settings.redirect_uris[0]),
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state or "state-123",
    }
    if resource is not None:
        params["resource"] = resource
    return params


@pytest.mark.asyncio
async def test_authorize_redirects_to_login_when_unauthenticated(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServer,
) -> None:
    verifier = "verifier"
    params = _authorize_params(oauth_settings, create_code_challenge(verifier))
    response = await async_client.get("/auth/oauth2/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert parsed.path == "/login/google"
    assert query["state"][0] == "state-123"


@pytest.mark.asyncio
async def test_authorize_returns_401_without_login_url(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> None:
    settings = oauth_settings.model_copy(update={"client_secret": SecretStr("test-secret"), "login_url": None})
    oauth_plugin = belgie_instance.add_plugin(settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    assert oauth_plugin.provider is not None
    oauth_plugin.provider.static_client = oauth_plugin.provider.static_client.model_copy(
        update={"skip_consent": True},
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        verifier = "verifier"
        params = _authorize_params(settings, create_code_challenge(verifier))
        response = await client.get("/auth/oauth2/authorize", params=params, follow_redirects=False)

    assert response.status_code == 400
    assert response.json() == {
        "error": "invalid_request",
        "error_description": "interaction url not configured",
    }


@pytest.mark.asyncio
async def test_authorize_redirects_when_prompt_create_and_signup_url_is_configured(
    belgie_instance: Belgie,
    oauth_settings: OAuthServer,
) -> None:
    settings = oauth_settings.model_copy(
        update={
            "client_secret": SecretStr("test-secret"),
            "login_url": None,
            "signup_url": "/signup",
        },
    )
    oauth_plugin = belgie_instance.add_plugin(settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    assert oauth_plugin.provider is not None
    oauth_plugin.provider.static_client = oauth_plugin.provider.static_client.model_copy(
        update={"skip_consent": True},
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        verifier = "verifier"
        params = _authorize_params(settings, create_code_challenge(verifier), state="state-create")
        params["prompt"] = "create"
        response = await client.get("/auth/oauth2/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert parsed.path == "/signup"
    assert query["state"][0] == "state-create"


@pytest.mark.asyncio
async def test_authorize_issues_code_without_login_url_when_authenticated(
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServer,
    create_individual_session,
) -> None:
    settings = oauth_settings.model_copy(update={"client_secret": SecretStr("test-secret"), "login_url": None})
    oauth_plugin = belgie_instance.add_plugin(settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    assert oauth_plugin.provider is not None
    oauth_plugin.provider.static_client = oauth_plugin.provider.static_client.model_copy(
        update={"skip_consent": True},
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = await create_individual_session(belgie_instance, db_session, "user@test.com")
        client.cookies.set(belgie_instance.settings.cookie.name, session_id)

        params = _authorize_params(settings, create_code_challenge("verifier"), state="state-auth")
        response = await client.get("/auth/oauth2/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "localhost"
    assert query["state"][0] == "state-auth"
    assert "code" in query


@pytest.mark.asyncio
async def test_authorize_issues_code_when_authenticated(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServer,
    create_individual_session,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "user@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    params = _authorize_params(oauth_settings, create_code_challenge("verifier"), state="state-auth")
    response = await async_client.get("/auth/oauth2/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "localhost"
    assert query["state"][0] == "state-auth"
    assert "code" in query


@pytest.mark.asyncio
async def test_authorize_issues_code_when_authenticated_via_post(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServer,
    create_individual_session,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "user@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    form_data = _authorize_params(oauth_settings, create_code_challenge("verifier"), state="state-auth-post")
    response = await async_client.post("/auth/oauth2/authorize", data=form_data, follow_redirects=False)

    assert response.status_code == 405


@pytest.mark.asyncio
async def test_authorize_rejects_unknown_resource(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServer,
) -> None:
    params = _authorize_params(
        oauth_settings,
        create_code_challenge("verifier"),
        resource="http://testserver/unknown-resource",
    )
    response = await async_client.get("/auth/oauth2/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.path == "/login/google"
    assert query["state"] == ["state-123"]


@pytest.mark.asyncio
async def test_authorize_accepts_configured_resource_when_authenticated(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServer,
    create_individual_session,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "user@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    params = _authorize_params(
        oauth_settings,
        create_code_challenge("verifier"),
        state="state-with-resource",
        resource="http://testserver/mcp",
    )
    response = await async_client.get("/auth/oauth2/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "localhost"
    assert query["state"][0] == "state-with-resource"
    assert "code" in query


@pytest.mark.asyncio
async def test_authorize_accepts_default_scopes_for_scope_less_dynamic_client(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_plugin,
    oauth_settings: OAuthServer,
    create_individual_session,
    seed_consent,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "dynamic-client@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    dynamic_client = await oauth_plugin._provider.register_client(
        OAuthServerClientMetadata(
            redirect_uris=["http://localhost/callback"],
            token_endpoint_auth_method="none",
        ),
    )
    await seed_consent(
        client_id=dynamic_client.client_id,
        session_id=session_id,
        scopes=list(oauth_settings.default_scopes),
    )
    params = {
        "response_type": "code",
        "client_id": dynamic_client.client_id,
        "redirect_uri": "http://localhost/callback",
        "scope": " ".join(oauth_settings.default_scopes),
        "code_challenge": create_code_challenge("dynamic-client-verifier"),
        "code_challenge_method": "S256",
        "state": "state-dynamic-client",
        "resource": "http://testserver/mcp",
    }

    response = await async_client.get("/auth/oauth2/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "localhost"
    assert query["state"][0] == "state-dynamic-client"
    assert "code" in query


@pytest.mark.asyncio
async def test_authorize_rejects_explicit_empty_scope(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServer,
    create_individual_session,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "empty-scope@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    params = _authorize_params(oauth_settings, create_code_challenge("empty-scope-verifier"), state="state-empty-scope")
    params["scope"] = ""
    response = await async_client.get("/auth/oauth2/authorize", params=params, follow_redirects=False)

    assert response.status_code == 400
    assert response.json()["detail"] == "missing scope"


@pytest.mark.asyncio
async def test_authorize_accepts_resource_without_trailing_slash_for_trailing_slash_configuration(
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServer,
    create_individual_session,
) -> None:
    settings = oauth_settings.model_copy(
        update={
            "client_secret": SecretStr("test-secret"),
            "valid_audiences": ["http://testserver/mcp/"],
        },
    )
    oauth_plugin = belgie_instance.add_plugin(settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    assert oauth_plugin.provider is not None
    oauth_plugin.provider.static_client = oauth_plugin.provider.static_client.model_copy(
        update={"skip_consent": True},
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = await create_individual_session(belgie_instance, db_session, "trailing-resource@test.com")
        client.cookies.set(belgie_instance.settings.cookie.name, session_id)

        params = _authorize_params(
            settings,
            create_code_challenge("verifier"),
            state="state-trailing-resource",
            resource="http://testserver/mcp",
        )
        response = await client.get("/auth/oauth2/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "localhost"
    assert query["state"][0] == "state-trailing-resource"
    assert "code" in query
