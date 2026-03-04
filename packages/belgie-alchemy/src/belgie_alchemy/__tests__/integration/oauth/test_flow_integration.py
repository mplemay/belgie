from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from belgie_core.core.belgie import Belgie
from belgie_core.core.client import BelgieClient
from belgie_oauth_server.client import OAuthServerClient
from belgie_oauth_server.settings import OAuthServer
from belgie_oauth_server.utils import construct_redirect_uri, create_code_challenge
from fastapi import Depends, FastAPI, Request
from fastapi.responses import RedirectResponse
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.mark.asyncio
async def test_full_oauth_flow(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServer,
    create_user_session,
) -> None:
    session_id = await create_user_session(belgie_instance, db_session, "user@test.com")
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
        context = await oauth.resolve_login_context(request)
        return RedirectResponse(url=construct_redirect_uri("/login/google", state=context.state), status_code=302)

    @app.get("/signup/custom")
    async def custom_signup(
        request: Request,
        oauth: OAuthServerClient = Depends(oauth_plugin),
        client: BelgieClient = Depends(belgie_instance),
    ) -> RedirectResponse:
        context = await oauth.resolve_login_context(request)
        response = RedirectResponse(url=context.return_to, status_code=302)
        _user, session = await client.sign_up("signup@example.com", request=request, name="Signup User")
        return client.create_session_cookie(session, response)

    @app.get("/login/google")
    async def login_google(
        request: Request,
        oauth: OAuthServerClient = Depends(oauth_plugin),
        client: BelgieClient = Depends(belgie_instance),
    ) -> RedirectResponse:
        context = await oauth.resolve_login_context(request)
        response = RedirectResponse(url=context.return_to, status_code=302)
        _user, session = await client.sign_up("google@example.com", request=request, name="Google User")
        return client.create_session_cookie(session, response)

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
