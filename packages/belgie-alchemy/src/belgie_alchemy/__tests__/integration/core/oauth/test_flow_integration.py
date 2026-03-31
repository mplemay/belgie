from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from belgie_core.core.belgie import Belgie
from belgie_core.core.client import BelgieClient
from belgie_oauth_server.client import OAuthServerClient
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.utils import construct_redirect_uri, create_code_challenge
from fastapi import Depends, FastAPI, Request, status
from fastapi.responses import RedirectResponse
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


def _build_custom_pages_app(belgie_instance: Belgie) -> tuple[FastAPI, OAuthServer]:
    settings = OAuthServer(
        base_url="http://testserver",
        prefix="/oauth",
        login_url="/login/custom",
        signup_url="/signup/custom",
        client_id="test-client",
        client_secret=SecretStr("test-secret"),
        redirect_uris=["http://testserver/callback"],
        default_scope="user",
    )
    oauth_plugin = belgie_instance.add_plugin(settings)

    app = FastAPI()
    app.include_router(belgie_instance.router)

    @app.get("/login/custom")
    async def custom_login(
        request: Request,
        oauth: OAuthServerClient = Depends(oauth_plugin),
    ) -> RedirectResponse:
        context = await oauth.try_resolve_login_context(request)
        if context is None:
            return RedirectResponse(
                url=construct_redirect_uri("/login/google", return_to=belgie_instance.settings.urls.signin_redirect),
                status_code=status.HTTP_302_FOUND,
            )
        if context.intent == "create":
            return RedirectResponse(
                url=construct_redirect_uri("/signup/custom", state=context.state),
                status_code=status.HTTP_302_FOUND,
            )
        return RedirectResponse(
            url=construct_redirect_uri("/login/google", state=context.state),
            status_code=status.HTTP_302_FOUND,
        )

    @app.get("/signup/custom")
    async def custom_signup(
        request: Request,
        oauth: OAuthServerClient = Depends(oauth_plugin),
        client: BelgieClient = Depends(belgie_instance),
    ) -> RedirectResponse:
        context = await oauth.try_resolve_login_context(request)
        redirect_target = context.return_to if context is not None else belgie_instance.settings.urls.signin_redirect
        response = RedirectResponse(url=redirect_target, status_code=status.HTTP_302_FOUND)
        _user, session = await client.sign_up("signup@example.com", request=request, name="Signup Individual")
        return client.create_session_cookie(session, response)

    @app.get("/login/google")
    async def login_google(
        request: Request,
        oauth: OAuthServerClient = Depends(oauth_plugin),
        client: BelgieClient = Depends(belgie_instance),
    ) -> RedirectResponse:
        context = await oauth.try_resolve_login_context(request)
        if context is None:
            return_to = request.query_params.get("return_to") or belgie_instance.settings.urls.signin_redirect
            return RedirectResponse(
                url=construct_redirect_uri("/mock/google/authorize", return_to=return_to),
                status_code=status.HTTP_302_FOUND,
            )
        response = RedirectResponse(url=context.return_to, status_code=status.HTTP_302_FOUND)
        _user, session = await client.sign_up("google@example.com", request=request, name="Google Individual")
        return client.create_session_cookie(session, response)

    return app, settings


@pytest.mark.asyncio
async def test_full_oauth_flow(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServer,
    create_individual_session,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "user@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    code_verifier = "verifier"
    code_challenge = create_code_challenge(code_verifier)

    authorize_response = await async_client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": oauth_settings.client_id,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_challenge": code_challenge,
            "state": "flow-state",
        },
        follow_redirects=False,
    )

    assert authorize_response.status_code == 302
    redirect_location = authorize_response.headers["location"]
    code = parse_qs(urlparse(redirect_location).query)["code"][0]

    token_response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "code": code,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_verifier": code_verifier,
        },
    )

    assert token_response.status_code == 200
    token_payload = token_response.json()
    access_token = token_payload["access_token"]

    introspect_response = await async_client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": access_token,
        },
    )

    assert introspect_response.status_code == 200
    assert introspect_response.json()["active"] is True


@pytest.mark.asyncio
async def test_full_oauth_flow_unauthenticated_with_custom_login_pages(
    belgie_instance: Belgie,
) -> None:
    app, settings = _build_custom_pages_app(belgie_instance)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        code_verifier = "verifier"
        authorize_response = await client.get(
            "/auth/oauth/authorize",
            params={
                "response_type": "code",
                "client_id": settings.client_id,
                "redirect_uri": str(settings.redirect_uris[0]),
                "code_challenge": create_code_challenge(code_verifier),
                "state": "custom-flow",
            },
            follow_redirects=False,
        )

        assert authorize_response.status_code == 302
        login_redirect = authorize_response.headers["location"]
        assert urlparse(login_redirect).path == "/auth/oauth/login"

        login_page_redirect = await client.get(login_redirect, follow_redirects=False)
        assert login_page_redirect.status_code == 302
        assert urlparse(login_page_redirect.headers["location"]).path == "/login/custom"

        provider_redirect = await client.get(login_page_redirect.headers["location"], follow_redirects=False)
        assert provider_redirect.status_code == 302, provider_redirect.text
        assert urlparse(provider_redirect.headers["location"]).path == "/login/google"

        callback_redirect = await client.get(provider_redirect.headers["location"], follow_redirects=False)
        assert callback_redirect.status_code == 302
        assert urlparse(callback_redirect.headers["location"]).path == "/auth/oauth/login/callback"

        code_redirect = await client.get(callback_redirect.headers["location"], follow_redirects=False)
        assert code_redirect.status_code == 302
        parsed_redirect = urlparse(code_redirect.headers["location"])
        query = parse_qs(parsed_redirect.query)
        assert parsed_redirect.path == "/callback"
        assert query["state"][0] == "custom-flow"
        assert "code" in query


@pytest.mark.asyncio
async def test_custom_login_route_supports_direct_entry_without_state(
    belgie_instance: Belgie,
) -> None:
    app, _settings = _build_custom_pages_app(belgie_instance)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        login_redirect = await client.get("/login/custom", follow_redirects=False)
        assert login_redirect.status_code == 302
        parsed_login_redirect = urlparse(login_redirect.headers["location"])
        login_query = parse_qs(parsed_login_redirect.query)
        assert parsed_login_redirect.path == "/login/google"
        assert login_query["return_to"][0] == belgie_instance.settings.urls.signin_redirect

        provider_redirect = await client.get(login_redirect.headers["location"], follow_redirects=False)
        assert provider_redirect.status_code == 302
        parsed_provider_redirect = urlparse(provider_redirect.headers["location"])
        provider_query = parse_qs(parsed_provider_redirect.query)
        assert parsed_provider_redirect.path == "/mock/google/authorize"
        assert provider_query["return_to"][0] == belgie_instance.settings.urls.signin_redirect


@pytest.mark.asyncio
async def test_custom_signup_route_supports_direct_entry_without_state(
    belgie_instance: Belgie,
) -> None:
    app, _settings = _build_custom_pages_app(belgie_instance)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/signup/custom", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == belgie_instance.settings.urls.signin_redirect
    assert belgie_instance.settings.cookie.name in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_custom_google_login_route_supports_direct_entry_without_state(
    belgie_instance: Belgie,
) -> None:
    app, _settings = _build_custom_pages_app(belgie_instance)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/login/google", follow_redirects=False)

    assert response.status_code == 302
    parsed_redirect = urlparse(response.headers["location"])
    query = parse_qs(parsed_redirect.query)
    assert parsed_redirect.path == "/mock/google/authorize"
    assert query["return_to"][0] == belgie_instance.settings.urls.signin_redirect


@pytest.mark.asyncio
async def test_custom_login_route_rejects_invalid_state(
    belgie_instance: Belgie,
) -> None:
    app, _settings = _build_custom_pages_app(belgie_instance)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/login/custom", params={"state": "invalid-state"}, follow_redirects=False)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid state parameter"


@pytest.mark.asyncio
async def test_custom_signup_route_rejects_invalid_state(
    belgie_instance: Belgie,
) -> None:
    app, _settings = _build_custom_pages_app(belgie_instance)

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.get("/signup/custom", params={"state": "invalid-state"}, follow_redirects=False)

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid state parameter"
