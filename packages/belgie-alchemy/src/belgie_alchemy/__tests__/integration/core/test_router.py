from collections.abc import AsyncGenerator, Callable
from urllib.parse import parse_qs, urlparse

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
def database(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> Callable[[], AsyncGenerator[AsyncSession, None]]:
    async def get_db() -> AsyncGenerator[AsyncSession, None]:
        async with db_session_factory() as session:
            yield session

    return get_db


@pytest_asyncio.fixture
async def adapter():
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
    db_session: AsyncSession,
) -> Belgie:
    _ = db_session
    belgie = Belgie(settings=auth_settings, adapter=adapter, database=database)
    belgie.add_plugin(
        GoogleOAuth(
            client_id="test-client-id",
            client_secret="test-client-secret",
            scopes=["openid", "email", "profile"],
        ),
    )
    return belgie


@pytest.fixture
def app(auth: Belgie, add_google_login_route) -> FastAPI:
    app = FastAPI()
    app.include_router(auth.router, dependencies=[])
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
def test_signin_google_endpoint_redirects(client: TestClient) -> None:
    _mock_google_discovery()
    response, provider_url, _ = _start_google_signin(client)

    assert response.status_code == 302
    assert "location" in response.headers
    assert response.headers["location"].startswith("http://localhost:8000/auth/provider/google/start?token=")
    assert provider_url.startswith("https://accounts.google.com/o/oauth2/v2/auth")
    assert "client_id=test-client-id" in provider_url
    assert "state=" in provider_url


def test_plugin_signin_route_removed(client: TestClient) -> None:
    response = client.get("/auth/provider/google/signin", follow_redirects=False)
    assert response.status_code == 404


@respx.mock
def test_signin_google_creates_oauth_state(client: TestClient, auth: Belgie, db_session: AsyncSession) -> None:
    _mock_google_discovery()
    _, _, state_param = _start_google_signin(client)

    import asyncio  # noqa: PLC0415

    async def check_state() -> None:
        oauth_state = await auth.adapter.get_oauth_state(db_session, state_param)
        assert oauth_state is not None
        assert oauth_state.state == state_param

    asyncio.run(check_state())


@respx.mock
def test_callback_redirects_to_relative_return_to(client: TestClient) -> None:
    _mock_google_discovery()
    _, _, state_param = _start_google_signin(client, "/login/google?return_to=%2Fafter")

    mock_token_response = {
        "access_token": "test-access-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }
    mock_user_info = {
        "id": "google-relative-redirect",
        "email": "relative@example.com",
        "verified_email": True,
    }

    respx.post(GoogleOAuthPlugin.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    callback = client.get(
        f"/auth/provider/google/callback?code=test-code&state={state_param}",
        follow_redirects=False,
    )

    assert callback.status_code == 302
    assert callback.headers["location"] == "/after"


@respx.mock
def test_callback_redirects_to_same_origin_absolute_return_to(client: TestClient) -> None:
    _mock_google_discovery()
    _, _, state_param = _start_google_signin(
        client,
        "/login/google?return_to=http%3A%2F%2Flocalhost%3A8000%2Fafter%3Ftab%3Dsecurity",
    )

    mock_token_response = {
        "access_token": "test-access-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }
    mock_user_info = {
        "id": "google-absolute-redirect",
        "email": "absolute@example.com",
        "verified_email": True,
    }

    respx.post(GoogleOAuthPlugin.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    callback = client.get(
        f"/auth/provider/google/callback?code=test-code&state={state_param}",
        follow_redirects=False,
    )

    assert callback.status_code == 302
    assert callback.headers["location"] == "http://localhost:8000/after?tab=security"


@respx.mock
def test_callback_rejects_cross_origin_return_to(client: TestClient) -> None:
    _mock_google_discovery()
    _, _, state_param = _start_google_signin(client, "/login/google?return_to=https%3A%2F%2Fexample.com%2Fpwn")

    mock_token_response = {
        "access_token": "test-access-token",
        "expires_in": 3600,
        "token_type": "Bearer",
        "scope": "openid email profile",
    }
    mock_user_info = {
        "id": "google-cross-origin-redirect",
        "email": "fallback@example.com",
        "verified_email": True,
    }

    respx.post(GoogleOAuthPlugin.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

    callback = client.get(
        f"/auth/provider/google/callback?code=test-code&state={state_param}",
        follow_redirects=False,
    )

    assert callback.status_code == 302
    assert callback.headers["location"] == "/dashboard"


@respx.mock
def test_callback_google_endpoint_success(client: TestClient, auth: Belgie, db_session: AsyncSession) -> None:
    _ = auth
    _ = db_session
    _mock_google_discovery()
    _, _, state_token = _start_google_signin(client)

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
        "name": "Test Individual",
        "picture": "https://example.com/photo.jpg",
    }

    respx.post(GoogleOAuthPlugin.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

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
    auth: Belgie,
    db_session: AsyncSession,
) -> None:
    _ = auth
    _ = db_session
    _mock_google_discovery()
    _, _, state_token = _start_google_signin(client)

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

    respx.post(GoogleOAuthPlugin.TOKEN_URL).mock(return_value=httpx.Response(200, json=mock_token_response))
    respx.get(GoogleOAuthPlugin.USER_INFO_URL).mock(return_value=httpx.Response(200, json=mock_user_info))

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
    from belgie_core.core.exceptions import InvalidStateError  # noqa: PLC0415

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


def test_signout_endpoint_deletes_session(client: TestClient, auth: Belgie, db_session: AsyncSession) -> None:
    import asyncio  # noqa: PLC0415

    async def setup_session() -> str:
        user = await auth.adapter.create_individual(db_session, email="signout@example.com")
        session = await auth.session_manager.create_session(db_session, individual_id=user.id)
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
