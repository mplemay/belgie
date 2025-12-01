from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

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
        secret="test-secret-key",
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
def adapter() -> AlchemyAdapter:
    return AlchemyAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    )


@pytest.fixture
def auth(auth_settings: AuthSettings, adapter: AlchemyAdapter, db_session: AsyncSession) -> Auth:
    # Include Google provider for router testing
    providers = {
        "google": GoogleProviderSettings(
            client_id="test-client-id",
            client_secret="test-client-secret",
            redirect_uri="http://localhost:8000/auth/provider/google/callback",
            scopes=["openid", "email", "profile"],
        ),
    }

    async def get_db_override() -> AsyncSession:
        return db_session

    fake_db = SimpleNamespace(dependency=get_db_override)

    return Auth(settings=auth_settings, adapter=adapter, providers=providers, db=fake_db)


@pytest.fixture
def app(auth: Auth) -> FastAPI:
    app = FastAPI()
    app.include_router(auth.router, dependencies=[])

    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def test_signin_google_endpoint_redirects(client: TestClient) -> None:
    response = client.get("/auth/provider/google/signin", follow_redirects=False)

    assert response.status_code == 302
    assert "location" in response.headers
    assert response.headers["location"].startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=test-client-id" in response.headers["location"]
    assert "state=" in response.headers["location"]


def test_signin_google_creates_oauth_state(client: TestClient, auth: Auth, db_session: AsyncSession) -> None:
    response = client.get("/auth/provider/google/signin", follow_redirects=False)

    location = response.headers["location"]
    state_param = [param.split("=")[1] for param in location.split("?")[1].split("&") if param.startswith("state=")][0]  # noqa: RUF015

    import asyncio  # noqa: PLC0415

    async def check_state() -> None:
        oauth_state = await auth.adapter.get_oauth_state(db_session, state_param)
        assert oauth_state is not None
        assert oauth_state.state == state_param

    asyncio.run(check_state())


@respx.mock
def test_callback_google_endpoint_success(client: TestClient, auth: Auth, db_session: AsyncSession) -> None:
    import asyncio  # noqa: PLC0415

    async def setup_state() -> str:
        state_token = "test-state-callback"  # noqa: S105
        await auth.adapter.create_oauth_state(
            db_session,
            state=state_token,
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None),
        )
        return state_token

    state_token = asyncio.run(setup_state())

    mock_token_response = {
        "access_token": "test-access-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
        "refresh_token": "test-refresh-token",
    }

    mock_user_info = {
        "id": "google-456",
        "email": "testuser@example.com",
        "verified_email": True,
        "name": "Test User",
        "picture": "https://example.com/photo.jpg",
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    response = client.get(
        f"/auth/provider/google/callback?code=test-code&state={state_token}",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    assert "belgie_session" in response.cookies
    assert response.cookies["belgie_session"] != ""


@respx.mock
def test_callback_google_sets_cookie_with_correct_attributes(
    client: TestClient,
    auth: Auth,
    db_session: AsyncSession,
) -> None:
    import asyncio  # noqa: PLC0415

    async def setup_state() -> str:
        state_token = "test-state-cookie"  # noqa: S105
        await auth.adapter.create_oauth_state(
            db_session,
            state=state_token,
            expires_at=(datetime.now(UTC) + timedelta(hours=1)).replace(tzinfo=None),
        )
        return state_token

    state_token = asyncio.run(setup_state())

    mock_token_response = {
        "access_token": "test-access-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }

    mock_user_info = {
        "id": "google-789",
        "email": "cookieuser@example.com",
        "verified_email": True,
    }

    respx.post(GoogleOAuthProvider.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthProvider.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    response = client.get(
        f"/auth/provider/google/callback?code=test-code&state={state_token}",
        follow_redirects=False,
    )

    cookie = response.cookies.get("belgie_session")
    assert cookie is not None

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "HttpOnly" in set_cookie_header
    assert "SameSite=lax" in set_cookie_header
    assert "Max-Age=3600" in set_cookie_header


def test_callback_google_invalid_state(client: TestClient) -> None:
    from belgie.auth.core.exceptions import InvalidStateError  # noqa: PLC0415

    with pytest.raises(InvalidStateError):
        client.get(
            "/auth/provider/google/callback?code=test-code&state=invalid-state",
            follow_redirects=False,
        )


def test_signout_endpoint_clears_cookie(client: TestClient) -> None:
    response = client.post("/auth/signout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/"

    set_cookie_header = response.headers.get("set-cookie", "")
    assert "belgie_session" in set_cookie_header
    assert "Max-Age=0" in set_cookie_header or "expires" in set_cookie_header.lower()


def test_signout_endpoint_deletes_session(client: TestClient, auth: Auth, db_session: AsyncSession) -> None:
    import asyncio  # noqa: PLC0415

    async def setup_session() -> str:
        user = await auth.adapter.create_user(db_session, email="signout@example.com")
        session = await auth.session_manager.create_session(db_session, user_id=user.id)
        return str(session.id)

    session_id = asyncio.run(setup_session())

    client.cookies.set("belgie_session", session_id)

    response = client.post("/auth/signout", follow_redirects=False)

    assert response.status_code == 302

    async def check_session_deleted() -> None:
        from uuid import UUID  # noqa: PLC0415

        session = await auth.session_manager.get_session(db_session, UUID(session_id))
        assert session is None

    asyncio.run(check_session_deleted())


def test_signout_endpoint_with_invalid_session_id(client: TestClient) -> None:
    client.cookies.set("belgie_session", "not-a-uuid")

    response = client.post("/auth/signout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/"


def test_signout_endpoint_without_cookie(client: TestClient) -> None:
    response = client.post("/auth/signout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "/"
