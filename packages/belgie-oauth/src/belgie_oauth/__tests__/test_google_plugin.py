from types import SimpleNamespace
from typing import Annotated
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import uuid4

import pytest
from belgie_core.core.exceptions import InvalidStateError
from belgie_oauth import GoogleOAuthClient, GoogleOAuthPlugin, GoogleOAuthSettings, GoogleUserInfo
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient


class DummyBelgie:
    def __init__(self, client) -> None:
        self._client = client
        self.settings = SimpleNamespace(
            base_url="http://localhost:8000",
            urls=SimpleNamespace(signin_redirect="/dashboard"),
        )

    async def __call__(self) -> object:
        return self._client


def _build_plugin() -> GoogleOAuthPlugin:
    settings = GoogleOAuthSettings(
        client_id="test-client-id",
        client_secret="test-client-secret",
        redirect_uri="http://localhost:8000/auth/provider/google/callback",
    )
    return GoogleOAuthPlugin(settings)


@pytest.mark.asyncio
async def test_dependency_requires_bind() -> None:
    plugin = _build_plugin()

    with pytest.raises(RuntimeError, match=r"Belgie.add_plugin"):
        await plugin()


def test_signin_url_persists_relative_return_to() -> None:
    plugin = _build_plugin()

    adapter = SimpleNamespace(create_oauth_state=AsyncMock())
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    plugin.bind(DummyBelgie(client_dependency))

    app = FastAPI()

    @app.get("/login")
    async def login(
        google: Annotated[GoogleOAuthClient, Depends(plugin)],
        return_to: str | None = None,
    ) -> dict[str, str]:
        return {"url": await google.signin_url(return_to=return_to)}

    response = TestClient(app).get("/login?return_to=%2Fafter", follow_redirects=False)

    assert response.status_code == 200
    assert response.json()["url"].startswith("https://accounts.google.com/o/oauth2/v2/auth")

    adapter.create_oauth_state.assert_awaited_once_with(
        client_dependency.db,
        state=ANY,
        expires_at=ANY,
        redirect_url="/after",
    )


def test_signin_url_persists_same_origin_absolute_return_to() -> None:
    plugin = _build_plugin()

    adapter = SimpleNamespace(create_oauth_state=AsyncMock())
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    plugin.bind(DummyBelgie(client_dependency))

    app = FastAPI()

    @app.get("/login")
    async def login(
        google: Annotated[GoogleOAuthClient, Depends(plugin)],
        return_to: str | None = None,
    ) -> dict[str, str]:
        return {"url": await google.signin_url(return_to=return_to)}

    response = TestClient(app).get(
        "/login?return_to=http%3A%2F%2Flocalhost%3A8000%2Fafter%3Ftab%3Dsecurity%23frag",
        follow_redirects=False,
    )

    assert response.status_code == 200

    adapter.create_oauth_state.assert_awaited_once_with(
        client_dependency.db,
        state=ANY,
        expires_at=ANY,
        redirect_url="http://localhost:8000/after?tab=security",
    )


def test_signin_url_rejects_cross_origin_return_to() -> None:
    plugin = _build_plugin()

    adapter = SimpleNamespace(create_oauth_state=AsyncMock())
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    plugin.bind(DummyBelgie(client_dependency))

    app = FastAPI()

    @app.get("/login")
    async def login(
        google: Annotated[GoogleOAuthClient, Depends(plugin)],
        return_to: str | None = None,
    ) -> dict[str, str]:
        return {"url": await google.signin_url(return_to=return_to)}

    response = TestClient(app).get("/login?return_to=https%3A%2F%2Fevil.example%2Fpwn", follow_redirects=False)

    assert response.status_code == 200

    adapter.create_oauth_state.assert_awaited_once_with(
        client_dependency.db,
        state=ANY,
        expires_at=ANY,
        redirect_url=None,
    )


def test_callback_uses_client_sign_up(monkeypatch) -> None:
    plugin = _build_plugin()

    oauth_state = SimpleNamespace(redirect_url="/custom-target")
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=oauth_state),
        delete_oauth_state=AsyncMock(return_value=True),
    )

    user = SimpleNamespace(id=uuid4())
    session = SimpleNamespace(id=uuid4())
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        sign_up=AsyncMock(return_value=(user, session)),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )

    monkeypatch.setattr(
        plugin,
        "exchange_code_for_tokens",
        AsyncMock(
            return_value={
                "access_token": "test-access-token",
                "token_type": "Bearer",
                "refresh_token": "test-refresh-token",
                "scope": "openid email profile",
                "id_token": "test-id-token",
                "expires_at": None,
            },
        ),
    )
    monkeypatch.setattr(
        plugin,
        "get_user_info",
        AsyncMock(
            return_value=GoogleUserInfo(
                id="google-user-123",
                email="person@example.com",
                verified_email=True,
                name="Test User",
                picture="https://example.com/photo.jpg",
            ),
        ),
    )

    app = FastAPI()
    app.include_router(plugin.router(DummyBelgie(client_dependency)), prefix="/auth")

    response = TestClient(app).get(
        "/auth/provider/google/callback?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/custom-target"

    client_dependency.sign_up.assert_awaited_once_with(
        "person@example.com",
        request=ANY,
        name="Test User",
        image="https://example.com/photo.jpg",
        email_verified=True,
    )

    client_dependency.upsert_oauth_account.assert_awaited_once_with(
        user_id=user.id,
        provider="google",
        provider_account_id="google-user-123",
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        expires_at=None,
        scope="openid email profile",
        token_type="Bearer",
        id_token="test-id-token",
    )

    client_dependency.create_session_cookie.assert_called_once_with(session, ANY)


def test_callback_falls_back_to_signin_redirect(monkeypatch) -> None:
    plugin = _build_plugin()

    oauth_state = SimpleNamespace(redirect_url=None)
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=oauth_state),
        delete_oauth_state=AsyncMock(return_value=True),
    )

    user = SimpleNamespace(id=uuid4())
    session = SimpleNamespace(id=uuid4())
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        sign_up=AsyncMock(return_value=(user, session)),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )

    monkeypatch.setattr(
        plugin,
        "exchange_code_for_tokens",
        AsyncMock(
            return_value={
                "access_token": "test-access-token",
                "token_type": "Bearer",
                "refresh_token": "test-refresh-token",
                "scope": "openid email profile",
                "id_token": "test-id-token",
                "expires_at": None,
            },
        ),
    )
    monkeypatch.setattr(
        plugin,
        "get_user_info",
        AsyncMock(
            return_value=GoogleUserInfo(
                id="google-user-123",
                email="person@example.com",
                verified_email=True,
                name="Test User",
                picture="https://example.com/photo.jpg",
            ),
        ),
    )

    app = FastAPI()
    app.include_router(plugin.router(DummyBelgie(client_dependency)), prefix="/auth")

    response = TestClient(app).get(
        "/auth/provider/google/callback?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"


def test_callback_invalid_state_raises() -> None:
    plugin = _build_plugin()

    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=None),
        delete_oauth_state=AsyncMock(return_value=False),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        sign_up=AsyncMock(),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(),
    )

    app = FastAPI()
    app.include_router(plugin.router(DummyBelgie(client_dependency)), prefix="/auth")

    with pytest.raises(InvalidStateError):
        TestClient(app).get(
            "/auth/provider/google/callback?code=test-code&state=invalid-state",
            follow_redirects=False,
        )
