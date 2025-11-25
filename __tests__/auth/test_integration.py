from uuid import UUID

import httpx
import pytest
import respx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from __tests__.auth.fixtures.models import Account, OAuthState, Session, User
from belgie.auth.adapters.alchemy import AlchemyAdapter
from belgie.auth.core.auth import Auth
from belgie.auth.core.settings import AuthSettings, CookieSettings, SessionSettings, URLSettings
from belgie.auth.providers.google import GoogleOAuthProvider, GoogleProviderSettings


@pytest.fixture
def auth_settings() -> AuthSettings:
    return AuthSettings(
        secret="integration-test-secret-key",
        base_url="http://localhost:8000",
        session=SessionSettings(
            max_age=3600,
            update_age=900,
        ),
        cookie=CookieSettings(
            name="belgie_session",
            secure=False,
            http_only=True,
            same_site="lax",
        ),
        urls=URLSettings(
            signin_redirect="/dashboard",
            signout_redirect="/",
        ),
    )


@pytest.fixture
def adapter(db_session: AsyncSession) -> AlchemyAdapter:
    async def get_db() -> AsyncSession:
        return db_session

    return AlchemyAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
        db_dependency=get_db,
    )


@pytest.fixture
def auth(auth_settings: AuthSettings, adapter: AlchemyAdapter) -> Auth:
    # Pass provider settings (not instances)
    providers = {
        "google": GoogleProviderSettings(
            client_id="integration-test-client-id",
            client_secret="integration-test-client-secret",
            redirect_uri="http://localhost:8000/auth/provider/google/callback",
            scopes=["openid", "email", "profile"],
        ),
    }

    return Auth(
        settings=auth_settings,
        adapter=adapter,
        providers=providers,
    )


@pytest.fixture
def app(auth: Auth) -> FastAPI:
    app = FastAPI()
    app.include_router(auth.router)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


@respx.mock
def test_full_oauth_flow_signin_to_callback(
    client: TestClient,
    auth: Auth,
    db_session: AsyncSession,
) -> None:
    import asyncio  # noqa: PLC0415

    signin_response = client.get("/auth/provider/google/signin", follow_redirects=False)

    assert signin_response.status_code == 302
    assert "location" in signin_response.headers
    location = signin_response.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth")

    state_param = [param.split("=")[1] for param in location.split("?")[1].split("&") if param.startswith("state=")][0]  # noqa: RUF015

    async def verify_state_created() -> None:
        oauth_state = await auth.adapter.get_oauth_state(db_session, state_param)
        assert oauth_state is not None
        assert oauth_state.state == state_param

    asyncio.run(verify_state_created())

    mock_token_response = {
        "access_token": "integration-access-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
        "refresh_token": "integration-refresh-token",
    }

    mock_user_info = {
        "id": "google-integration-123",
        "email": "integration@example.com",
        "verified_email": True,
        "name": "Integration User",
        "picture": "https://example.com/photo.jpg",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    callback_response = client.get(
        f"/auth/provider/google/callback?code=test-code&state={state_param}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    assert callback_response.headers["location"] == "/dashboard"
    assert "belgie_session" in callback_response.cookies

    session_id = callback_response.cookies["belgie_session"]

    async def verify_user_and_session_created() -> None:
        user = await auth.adapter.get_user_by_email(db_session, "integration@example.com")
        assert user is not None
        assert user.email == "integration@example.com"
        assert user.name == "Integration User"
        assert user.email_verified is True

        session = await auth.session_manager.get_session(db_session, UUID(session_id))
        assert session is not None
        assert session.user_id == user.id

        account = await auth.adapter.get_account_by_user_and_provider(db_session, user.id, "google")
        assert account is not None
        assert account.provider_account_id == "google-integration-123"
        assert account.access_token == "integration-access-token"  # noqa: S105
        assert account.scope == "openid email profile"

        state_deleted = await auth.adapter.get_oauth_state(db_session, state_param)
        assert state_deleted is None

    asyncio.run(verify_user_and_session_created())


@respx.mock
def test_signout_flow(client: TestClient, auth: Auth, db_session: AsyncSession) -> None:
    import asyncio  # noqa: PLC0415

    signin_response = client.get("/auth/provider/google/signin", follow_redirects=False)
    location = signin_response.headers["location"]
    state_param = [param.split("=")[1] for param in location.split("?")[1].split("&") if param.startswith("state=")][0]  # noqa: RUF015

    mock_token_response = {
        "access_token": "signout-access-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }

    mock_user_info = {
        "id": "google-signout-202",
        "email": "signoutuser@example.com",
        "verified_email": True,
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    callback_response = client.get(
        f"/auth/provider/google/callback?code=signout-code&state={state_param}",
        follow_redirects=False,
    )

    session_id = callback_response.cookies["belgie_session"]

    async def verify_session_exists() -> None:
        session = await auth.session_manager.get_session(db_session, UUID(session_id))
        assert session is not None

    asyncio.run(verify_session_exists())

    client.cookies.set("belgie_session", session_id)
    signout_response = client.post("/auth/signout", follow_redirects=False)

    assert signout_response.status_code == 302
    assert signout_response.headers["location"] == "/"

    set_cookie_header = signout_response.headers.get("set-cookie", "")
    assert "belgie_session" in set_cookie_header
    assert "Max-Age=0" in set_cookie_header or "expires" in set_cookie_header.lower()

    async def verify_session_deleted() -> None:
        session = await auth.session_manager.get_session(db_session, UUID(session_id))
        assert session is None

    asyncio.run(verify_session_deleted())


@respx.mock
def test_existing_user_signin(client: TestClient, auth: Auth, db_session: AsyncSession) -> None:
    import asyncio  # noqa: PLC0415

    async def create_existing_user() -> str:
        user = await auth.adapter.create_user(db_session, email="existing@example.com", name="Existing User")
        return str(user.id)

    user_id = asyncio.run(create_existing_user())

    signin_response = client.get("/auth/provider/google/signin", follow_redirects=False)
    location = signin_response.headers["location"]
    state_param = [param.split("=")[1] for param in location.split("?")[1].split("&") if param.startswith("state=")][0]  # noqa: RUF015

    mock_token_response = {
        "access_token": "existing-user-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }

    mock_user_info = {
        "id": "google-existing-404",
        "email": "existing@example.com",
        "verified_email": True,
        "name": "Existing User",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    callback_response = client.get(
        f"/auth/provider/google/callback?code=existing-code&state={state_param}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 302

    async def verify_existing_user_reused() -> None:
        user = await auth.adapter.get_user_by_email(db_session, "existing@example.com")
        assert user is not None
        assert str(user.id) == user_id

        account = await auth.adapter.get_account_by_user_and_provider(db_session, user.id, "google")
        assert account is not None
        assert account.provider_account_id == "google-existing-404"

    asyncio.run(verify_existing_user_reused())


@respx.mock
def test_multiple_concurrent_sessions(client: TestClient, auth: Auth, db_session: AsyncSession) -> None:
    import asyncio  # noqa: PLC0415

    signin1 = client.get("/auth/provider/google/signin", follow_redirects=False)
    signin2 = client.get("/auth/provider/google/signin", follow_redirects=False)

    state1 = [  # noqa: RUF015
        param.split("=")[1]
        for param in signin1.headers["location"].split("?")[1].split("&")
        if param.startswith("state=")
    ][0]
    state2 = [  # noqa: RUF015
        param.split("=")[1]
        for param in signin2.headers["location"].split("?")[1].split("&")
        if param.startswith("state=")
    ][0]

    assert state1 != state2

    mock_token_response = {
        "access_token": "concurrent-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }

    mock_user_info = {
        "id": "google-concurrent-505",
        "email": "concurrent@example.com",
        "verified_email": True,
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    callback1 = client.get(f"/auth/provider/google/callback?code=code1&state={state1}", follow_redirects=False)
    callback2 = client.get(f"/auth/provider/google/callback?code=code2&state={state2}", follow_redirects=False)

    assert callback1.status_code == 302
    assert callback2.status_code == 302

    session1_id = callback1.cookies["belgie_session"]
    session2_id = callback2.cookies["belgie_session"]

    assert session1_id != session2_id

    async def verify_both_sessions_same_user() -> None:
        session1 = await auth.session_manager.get_session(db_session, UUID(session1_id))
        session2 = await auth.session_manager.get_session(db_session, UUID(session2_id))

        assert session1 is not None
        assert session2 is not None
        assert session1.user_id == session2.user_id

    asyncio.run(verify_both_sessions_same_user())
