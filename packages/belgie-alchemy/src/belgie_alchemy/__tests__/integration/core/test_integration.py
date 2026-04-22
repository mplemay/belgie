from collections.abc import AsyncGenerator, Callable
from urllib.parse import parse_qs, urlparse
from uuid import UUID

import httpx
import pytest
import pytest_asyncio
import respx
from belgie_core.core.belgie import Belgie
from belgie_core.core.settings import BelgieSettings, CookieSettings, SessionSettings, URLSettings
from belgie_oauth import GoogleOAuth, GoogleOAuthPlugin
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from belgie_alchemy.__tests__.fixtures.core.models import Account, Individual, OAuthAccount, OAuthState, Session
from belgie_alchemy.core import BelgieAdapter


@pytest.fixture
def auth_settings() -> BelgieSettings:
    return BelgieSettings(
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
def database(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], AsyncGenerator[AsyncSession, None]]:
    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with db_session_factory() as session:
            yield session

    return get_db


@pytest_asyncio.fixture
async def adapter(db_session: AsyncSession):
    adapter = BelgieAdapter(
        account=Account,
        individual=Individual,
        oauth_account=OAuthAccount,
        session=Session,
        oauth_state=OAuthState,
    )
    yield adapter


@pytest.fixture
def auth(
    auth_settings: BelgieSettings,
    adapter: BelgieAdapter,
    database: Callable[[], AsyncGenerator[AsyncSession, None]],
) -> Belgie:
    belgie = Belgie(
        settings=auth_settings,
        adapter=adapter,
        database=database,
    )
    belgie.add_plugin(
        GoogleOAuth(
            client_id="integration-test-client-id",
            client_secret="integration-test-client-secret",
            scopes=["openid", "email", "profile"],
        ),
    )
    return belgie


@pytest.fixture
def app(auth: Belgie, add_google_login_route) -> FastAPI:
    app = FastAPI()
    app.include_router(auth.router)
    add_google_login_route(app, auth)
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


def _mock_google_discovery() -> None:
    respx.get(GoogleOAuthPlugin.DISCOVERY_URL).mock(
        return_value=httpx.Response(
            200,
            json={
                "authorization_endpoint": "https://accounts.google.com/o/oauth2/v2/auth",
                "token_endpoint": GoogleOAuthPlugin.TOKEN_URL,
                "userinfo_endpoint": GoogleOAuthPlugin.USER_INFO_URL,
                "issuer": "https://accounts.google.com",
                "jwks_uri": "https://www.googleapis.com/oauth2/v3/certs",
            },
        ),
    )


def _path_and_query(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path


def _start_google_signin(client: TestClient, path: str = "/login/google") -> tuple[httpx.Response, str, str]:
    signin_response = client.get(path, follow_redirects=False)
    provider_response = client.get(_path_and_query(signin_response.headers["location"]), follow_redirects=False)
    provider_url = provider_response.headers["location"]
    state = parse_qs(urlparse(provider_url).query)["state"][0]
    return signin_response, provider_url, state


@respx.mock
def test_full_oauth_flow_signin_to_callback(
    client: TestClient,
    auth: Belgie,
    db_session: AsyncSession,
) -> None:
    import asyncio  # noqa: PLC0415

    _mock_google_discovery()
    signin_response, provider_url, state_param = _start_google_signin(client)

    assert signin_response.status_code == 302
    assert "location" in signin_response.headers
    assert signin_response.headers["location"].startswith("http://localhost:8000/auth/provider/google/start?token=")
    assert provider_url.startswith("https://accounts.google.com/o/oauth2/v2/auth")

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
        "name": "Integration Individual",
        "picture": "https://example.com/photo.jpg",
    }

    respx.post(GoogleOAuthPlugin.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    callback_response = client.get(
        f"/auth/provider/google/callback?code=test-code&state={state_param}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 302
    assert callback_response.headers["location"] == "/dashboard"
    assert "belgie_session" in callback_response.cookies

    session_id = callback_response.cookies["belgie_session"]

    async def verify_user_and_session_created() -> None:
        user = await auth.adapter.get_individual_by_email(db_session, "integration@example.com")
        assert user is not None
        assert user.email == "integration@example.com"
        assert user.name == "Integration Individual"
        assert user.email_verified_at is not None

        session = await auth.session_manager.get_session(db_session, UUID(session_id))
        assert session is not None
        assert session.individual_id == user.id

        account = await auth.adapter.get_oauth_account_by_individual_and_provider(db_session, user.id, "google")
        assert account is not None
        assert account.provider_account_id == "google-integration-123"
        assert account.access_token == "integration-access-token"  # noqa: S105
        assert account.scope == "openid email profile"

        state_deleted = await auth.adapter.get_oauth_state(db_session, state_param)
        assert state_deleted is None

    asyncio.run(verify_user_and_session_created())


@respx.mock
def test_signout_flow(client: TestClient, auth: Belgie, db_session: AsyncSession) -> None:
    import asyncio  # noqa: PLC0415

    _mock_google_discovery()
    _, _, state_param = _start_google_signin(client)

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

    respx.post(GoogleOAuthPlugin.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

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
def test_existing_user_signin(client: TestClient, auth: Belgie, db_session: AsyncSession) -> None:
    import asyncio  # noqa: PLC0415

    async def create_existing_user() -> str:
        user = await auth.adapter.create_individual(
            db_session,
            email="existing@example.com",
            name="Existing Individual",
        )
        return str(user.id)

    individual_id = asyncio.run(create_existing_user())

    _mock_google_discovery()
    _, _, state_param = _start_google_signin(client)

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
        "name": "Existing Individual",
    }

    respx.post(GoogleOAuthPlugin.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    callback_response = client.get(
        f"/auth/provider/google/callback?code=existing-code&state={state_param}",
        follow_redirects=False,
    )

    assert callback_response.status_code == 302

    async def verify_existing_user_reused() -> None:
        user = await auth.adapter.get_individual_by_email(db_session, "existing@example.com")
        assert user is not None
        assert str(user.id) == individual_id

        account = await auth.adapter.get_oauth_account_by_individual_and_provider(db_session, user.id, "google")
        assert account is not None
        assert account.provider_account_id == "google-existing-404"

    asyncio.run(verify_existing_user_reused())


@respx.mock
def test_multiple_concurrent_sessions(app: FastAPI, auth: Belgie, db_session: AsyncSession) -> None:
    import asyncio  # noqa: PLC0415

    _mock_google_discovery()
    with TestClient(app) as first_client, TestClient(app) as second_client:
        _, _, state1 = _start_google_signin(first_client)
        _, _, state2 = _start_google_signin(second_client)

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

        respx.post(GoogleOAuthPlugin.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
        respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

        callback1 = first_client.get(
            f"/auth/provider/google/callback?code=code1&state={state1}",
            follow_redirects=False,
        )
        callback2 = second_client.get(
            f"/auth/provider/google/callback?code=code2&state={state2}",
            follow_redirects=False,
        )

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
            assert session1.individual_id == session2.individual_id

        asyncio.run(verify_both_sessions_same_user())
