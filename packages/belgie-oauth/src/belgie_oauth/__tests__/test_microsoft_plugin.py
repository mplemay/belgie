from types import SimpleNamespace
from typing import Annotated
from unittest.mock import ANY, AsyncMock, MagicMock
from uuid import uuid4

import pytest
from belgie_core.core.exceptions import InvalidStateError
from belgie_core.core.settings import BelgieSettings
from belgie_oauth import MicrosoftOAuth, MicrosoftOAuthClient, MicrosoftOAuthPlugin, MicrosoftUserInfo
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient


class DummyBelgie:
    def __init__(self, client) -> None:
        self._client = client
        self.settings = SimpleNamespace(
            base_url="http://localhost:8000",
            urls=SimpleNamespace(signin_redirect="/dashboard"),
        )
        self.after_authenticate = AsyncMock()

    async def __call__(self) -> object:
        return self._client


def _build_plugin() -> MicrosoftOAuthPlugin:
    settings = MicrosoftOAuth(
        client_id="test-client-id",
        client_secret="test-client-secret",
    )
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    return MicrosoftOAuthPlugin(belgie_settings, settings)


@pytest.mark.asyncio
async def test_dependency_requires_router_initialization() -> None:
    plugin = _build_plugin()

    with pytest.raises(RuntimeError, match=r"router initialization"):
        await plugin()


def test_signin_url_persists_relative_return_to() -> None:
    plugin = _build_plugin()

    adapter = SimpleNamespace(create_oauth_state=AsyncMock())
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    plugin.router(DummyBelgie(client_dependency))

    app = FastAPI()

    @app.get("/login")
    async def login(
        microsoft: Annotated[MicrosoftOAuthClient, Depends(plugin)],
        return_to: str | None = None,
    ) -> dict[str, str]:
        return {"url": await microsoft.signin_url(return_to=return_to)}

    response = TestClient(app).get("/login?return_to=%2Fafter", follow_redirects=False)

    assert response.status_code == 200
    assert response.json()["url"].startswith("https://login.microsoftonline.com/common/oauth2/v2.0/authorize")

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
    plugin.router(DummyBelgie(client_dependency))

    app = FastAPI()

    @app.get("/login")
    async def login(
        microsoft: Annotated[MicrosoftOAuthClient, Depends(plugin)],
        return_to: str | None = None,
    ) -> dict[str, str]:
        return {"url": await microsoft.signin_url(return_to=return_to)}

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
    plugin.router(DummyBelgie(client_dependency))

    app = FastAPI()

    @app.get("/login")
    async def login(
        microsoft: Annotated[MicrosoftOAuthClient, Depends(plugin)],
        return_to: str | None = None,
    ) -> dict[str, str]:
        return {"url": await microsoft.signin_url(return_to=return_to)}

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
            return_value=SimpleNamespace(
                access_token="test-access-token",
                token_type="Bearer",
                refresh_token="test-refresh-token",
                scope="openid profile email offline_access User.Read",
                id_token="test-id-token",
                expires_at=None,
            ),
        ),
    )
    monkeypatch.setattr(
        plugin,
        "get_user_info",
        AsyncMock(
            return_value=MicrosoftUserInfo(
                sub="microsoft-user-123",
                preferred_username="person@example.com",
                name="Test Individual",
                picture="https://example.com/photo.jpg",
            ),
        ),
    )

    belgie = DummyBelgie(client_dependency)
    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    response = TestClient(app).get(
        "/auth/provider/microsoft/callback?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/custom-target"

    client_dependency.sign_up.assert_awaited_once_with(
        "person@example.com",
        request=ANY,
        name="Test Individual",
        image="https://example.com/photo.jpg",
        email_verified_at=None,
    )

    client_dependency.upsert_oauth_account.assert_awaited_once_with(
        individual_id=user.id,
        provider="microsoft",
        provider_account_id="microsoft-user-123",
        access_token="test-access-token",
        refresh_token="test-refresh-token",
        expires_at=None,
        scope="openid profile email offline_access User.Read",
        token_type="Bearer",
        id_token="test-id-token",
    )

    client_dependency.create_session_cookie.assert_called_once_with(session, ANY)
    belgie.after_authenticate.assert_awaited_once()
    profile = belgie.after_authenticate.await_args.kwargs["profile"]
    assert profile.provider == "microsoft"
    assert profile.email == "person@example.com"
    assert profile.email_verified is False


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
            return_value=SimpleNamespace(
                access_token="test-access-token",
                token_type="Bearer",
                refresh_token="test-refresh-token",
                scope="openid profile email offline_access User.Read",
                id_token="test-id-token",
                expires_at=None,
            ),
        ),
    )
    monkeypatch.setattr(
        plugin,
        "get_user_info",
        AsyncMock(
            return_value=MicrosoftUserInfo(
                sub="microsoft-user-123",
                email="person@example.com",
                name="Test Individual",
                picture="https://example.com/photo.jpg",
            ),
        ),
    )

    belgie = DummyBelgie(client_dependency)
    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    response = TestClient(app).get(
        "/auth/provider/microsoft/callback?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    belgie.after_authenticate.assert_awaited_once()


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
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(DummyBelgie(client_dependency)))
    app.include_router(auth_router)

    with pytest.raises(InvalidStateError):
        TestClient(app).get(
            "/auth/provider/microsoft/callback?code=test-code&state=invalid-state",
            follow_redirects=False,
        )
