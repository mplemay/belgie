from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import ANY, AsyncMock, MagicMock
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

import httpx
import pytest
import respx
from belgie_core.core.exceptions import InvalidStateError, OAuthError
from belgie_core.core.settings import BelgieSettings
from belgie_oauth import OAuthLinkedAccount, OAuthPlugin, OAuthProvider, OAuthTokenSet, OAuthUserInfo
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError


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


def _build_plugin(**provider_overrides: object) -> OAuthPlugin:
    belgie_settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    provider_config = {
        "provider_id": "acme",
        "client_id": "test-client-id",
        "client_secret": SecretStr("test-client-secret"),
        "authorization_endpoint": "https://idp.example.com/oauth2/authorize",
        "token_endpoint": "https://idp.example.com/oauth2/token",
        "userinfo_endpoint": "https://idp.example.com/userinfo",
        "scopes": ["openid", "email", "profile"],
        "access_type": "offline",
        "prompt": "consent",
    }
    provider_config.update(provider_overrides)
    provider = OAuthProvider(**provider_config)
    return OAuthPlugin(belgie_settings, provider)


def _build_state(**overrides: object) -> SimpleNamespace:
    data = {
        "state": "test-state",
        "provider": "acme",
        "individual_id": None,
        "code_verifier": "test-verifier",
        "nonce": "test-nonce",
        "intent": "signin",
        "redirect_url": "/after",
        "error_redirect_url": None,
        "new_user_redirect_url": None,
        "payload": None,
        "request_sign_up": False,
        "expires_at": datetime.now(UTC).replace(tzinfo=None) + timedelta(minutes=5),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _build_account(**overrides: object) -> SimpleNamespace:
    data = {
        "id": uuid4(),
        "individual_id": uuid4(),
        "provider": "acme",
        "provider_account_id": "provider-account-1",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        "token_type": "Bearer",
        "scope": "openid email profile",
        "id_token": None,
        "created_at": datetime.now(UTC).replace(tzinfo=None),
        "updated_at": datetime.now(UTC).replace(tzinfo=None),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _build_app(plugin: OAuthPlugin, client_dependency) -> FastAPI:
    belgie = DummyBelgie(client_dependency)
    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)
    app.state.belgie = belgie
    return app


def _token_set(**overrides: object) -> OAuthTokenSet:
    data = {
        "access_token": "access-token",
        "token_type": "Bearer",
        "refresh_token": "refresh-token",
        "scope": "openid email profile",
        "id_token": "id-token",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        "raw": {
            "access_token": "access-token",
            "refresh_token": "refresh-token",
            "scope": "openid email profile",
            "id_token": "id-token",
            "token_type": "Bearer",
        },
    }
    data.update(overrides)
    return OAuthTokenSet(**data)


def _linked_account(**overrides: object) -> OAuthLinkedAccount:
    data = {
        "id": uuid4(),
        "individual_id": uuid4(),
        "provider": "acme",
        "provider_account_id": "provider-account-1",
        "access_token": "access-token",
        "refresh_token": "refresh-token",
        "expires_at": datetime.now(UTC) + timedelta(hours=1),
        "token_type": "Bearer",
        "scope": "openid email profile",
        "id_token": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    data.update(overrides)
    return OAuthLinkedAccount(**data)


def test_provider_requires_discovery_or_manual_endpoints() -> None:
    with pytest.raises(ValidationError):
        OAuthProvider(
            provider_id="acme",
            client_id="client-id",
            client_secret=SecretStr("client-secret"),
        )


def test_dependency_requires_router_initialization() -> None:
    plugin = _build_plugin()

    with pytest.raises(RuntimeError, match=r"router initialization"):
        plugin()


@pytest.mark.asyncio
async def test_signin_url_persists_pkce_nonce_payload_and_redirects() -> None:
    plugin = _build_plugin()
    adapter = SimpleNamespace(create_oauth_state=AsyncMock())
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    url = await oauth_client.signin_url(
        return_to="/after",
        error_redirect_url="/error",
        new_user_redirect_url="/welcome",
        payload={"source": "landing"},
        request_sign_up=True,
    )

    adapter.create_oauth_state.assert_awaited_once_with(
        client_dependency.db,
        state=ANY,
        expires_at=ANY,
        provider="acme",
        code_verifier=ANY,
        nonce=ANY,
        intent="signin",
        redirect_url="/after",
        error_redirect_url="/error",
        new_user_redirect_url="/welcome",
        payload={"source": "landing"},
        request_sign_up=True,
        individual_id=None,
    )

    parsed = urlparse(url)
    query = parse_qs(parsed.query)
    assert parsed.netloc == "idp.example.com"
    assert query["prompt"][0] == "consent"
    assert query["access_type"][0] == "offline"
    assert query["nonce"][0]
    assert query["code_challenge"][0]
    assert query["code_challenge_method"][0] == "S256"


@pytest.mark.asyncio
async def test_link_url_persists_link_intent_and_individual() -> None:
    plugin = _build_plugin()
    adapter = SimpleNamespace(create_oauth_state=AsyncMock())
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    individual_id = uuid4()
    url = await oauth_client.link_url(
        individual_id=individual_id,
        return_to="/linked",
        payload={"flow": "link"},
    )

    assert url.startswith("https://idp.example.com/oauth2/authorize")
    adapter.create_oauth_state.assert_awaited_once_with(
        client_dependency.db,
        state=ANY,
        expires_at=ANY,
        provider="acme",
        code_verifier=ANY,
        nonce=ANY,
        intent="link",
        redirect_url="/linked",
        error_redirect_url=None,
        new_user_redirect_url=None,
        payload={"flow": "link"},
        request_sign_up=False,
        individual_id=individual_id,
    )


@pytest.mark.asyncio
async def test_signin_url_supports_additional_scope_reconsent() -> None:
    plugin = _build_plugin()
    client_dependency = SimpleNamespace(db=object(), adapter=SimpleNamespace(create_oauth_state=AsyncMock()))
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    url = await oauth_client.signin_url(
        scopes=["openid", "email", "calendar.read"],
        prompt="select_account",
        payload={"scope": "expanded"},
    )

    query = parse_qs(urlparse(url).query)
    assert query["scope"][0] == "openid email calendar.read"
    assert query["prompt"][0] == "select_account"


@pytest.mark.asyncio
@respx.mock
async def test_resolve_server_metadata_uses_discovery_and_caches() -> None:
    discovery_url = "https://accounts.example.com/.well-known/openid-configuration"
    plugin = _build_plugin(
        discovery_url=discovery_url,
        authorization_endpoint=None,
        token_endpoint=None,
        userinfo_endpoint=None,
    )
    respx.get(discovery_url).mock(
        return_value=httpx.Response(
            200,
            json={
                "authorization_endpoint": "https://accounts.example.com/authorize",
                "token_endpoint": "https://accounts.example.com/token",
                "userinfo_endpoint": "https://accounts.example.com/userinfo",
                "issuer": "https://accounts.example.com",
                "jwks_uri": "https://accounts.example.com/jwks",
            },
        ),
    )

    metadata_first = await plugin.resolve_server_metadata()
    metadata_second = await plugin.resolve_server_metadata()

    assert metadata_first["authorization_endpoint"] == "https://accounts.example.com/authorize"
    assert metadata_second["issuer"] == "https://accounts.example.com"
    assert len(respx.calls) == 1


@pytest.mark.asyncio
@respx.mock
async def test_exchange_code_for_tokens_uses_manual_token_endpoint() -> None:
    plugin = _build_plugin()
    respx.post("https://idp.example.com/oauth2/token").mock(
        return_value=httpx.Response(
            200,
            json={
                "access_token": "new-access-token",
                "refresh_token": "new-refresh-token",
                "token_type": "Bearer",
                "scope": "openid email profile",
                "expires_in": 3600,
                "id_token": "test-id-token",
            },
        ),
    )

    token_set = await plugin.exchange_code_for_tokens("test-code", code_verifier="verifier")

    assert token_set.access_token == "new-access-token"  # noqa: S105
    assert token_set.refresh_token == "new-refresh-token"  # noqa: S105
    assert token_set.id_token == "test-id-token"  # noqa: S105
    assert token_set.expires_at is not None


def test_callback_signin_new_user_exposes_payload_on_request_state(monkeypatch) -> None:
    plugin = _build_plugin()
    oauth_state = _build_state(
        payload={"flow": "signin"},
        request_sign_up=True,
        new_user_redirect_url="/welcome",
    )
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=oauth_state),
        delete_oauth_state=AsyncMock(return_value=True),
        get_individual_by_email=AsyncMock(return_value=None),
        get_individual_by_id=AsyncMock(return_value=None),
    )
    user = SimpleNamespace(id=uuid4(), email="person@example.com")
    session = SimpleNamespace(id=uuid4())
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=None),
        get_or_create_individual=AsyncMock(return_value=(user, True)),
        sign_in_individual=AsyncMock(return_value=session),
        after_sign_up=AsyncMock(),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )

    monkeypatch.setattr(
        plugin,
        "resolve_server_metadata",
        AsyncMock(
            return_value={
                "token_endpoint": "https://idp.example.com/oauth2/token",
                "userinfo_endpoint": "https://idp.example.com/userinfo",
                "issuer": "https://idp.example.com",
            },
        ),
    )
    monkeypatch.setattr(plugin, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
    monkeypatch.setattr(
        plugin,
        "_fetch_provider_profile",
        AsyncMock(
            return_value=OAuthUserInfo(
                provider_account_id="provider-account-1",
                email="person@example.com",
                email_verified=True,
                name="Test Person",
                image="https://example.com/photo.jpg",
                raw={"sub": "provider-account-1"},
            ),
        ),
    )

    app = _build_app(plugin, client_dependency)
    response = TestClient(app).get(
        "/auth/provider/acme/callback?code=test-code&state=test-state&iss=https%3A%2F%2Fidp.example.com",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/welcome"
    client_dependency.after_sign_up.assert_awaited_once()
    client_dependency.upsert_oauth_account.assert_awaited_once_with(
        individual_id=user.id,
        provider="acme",
        provider_account_id="provider-account-1",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=ANY,
        scope="openid email profile",
        token_type="Bearer",
        id_token="id-token",
    )

    request = app.state.belgie.after_authenticate.await_args.kwargs["request"]
    assert request.state.oauth_payload == {"flow": "signin"}
    assert request.state.oauth_state.intent == "signin"
    assert request.state.oauth_state.request_sign_up is True


def test_callback_link_flow_does_not_set_cookie(monkeypatch) -> None:
    plugin = _build_plugin()
    individual_id = uuid4()
    oauth_state = _build_state(
        intent="link",
        individual_id=individual_id,
        redirect_url="/linked",
        payload={"flow": "link"},
    )
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=oauth_state),
        delete_oauth_state=AsyncMock(return_value=True),
        get_individual_by_id=AsyncMock(return_value=SimpleNamespace(id=individual_id)),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=None),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )

    monkeypatch.setattr(
        plugin,
        "resolve_server_metadata",
        AsyncMock(return_value={"token_endpoint": "https://idp.example.com/oauth2/token"}),
    )
    monkeypatch.setattr(plugin, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
    monkeypatch.setattr(
        plugin,
        "_fetch_provider_profile",
        AsyncMock(
            return_value=OAuthUserInfo(
                provider_account_id="provider-account-2",
                email="linked@example.com",
                email_verified=True,
                raw={"sub": "provider-account-2"},
            ),
        ),
    )

    app = _build_app(plugin, client_dependency)
    response = TestClient(app).get(
        "/auth/provider/acme/callback?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/linked"
    client_dependency.upsert_oauth_account.assert_awaited_once_with(
        individual_id=individual_id,
        provider="acme",
        provider_account_id="provider-account-2",
        access_token="access-token",
        refresh_token="refresh-token",
        expires_at=ANY,
        scope="openid email profile",
        token_type="Bearer",
        id_token="id-token",
    )
    client_dependency.create_session_cookie.assert_not_called()
    app.state.belgie.after_authenticate.assert_not_awaited()


def test_callback_rejects_invalid_state() -> None:
    plugin = _build_plugin()
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=SimpleNamespace(get_oauth_state=AsyncMock(return_value=None)),
    )
    app = _build_app(plugin, client_dependency)

    with pytest.raises(InvalidStateError):
        TestClient(app).get("/auth/provider/acme/callback?code=test-code&state=missing")


def test_callback_rejects_issuer_mismatch(monkeypatch) -> None:
    plugin = _build_plugin()
    oauth_state = _build_state()
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=SimpleNamespace(
            get_oauth_state=AsyncMock(return_value=oauth_state),
            delete_oauth_state=AsyncMock(return_value=True),
        ),
    )
    monkeypatch.setattr(
        plugin,
        "resolve_server_metadata",
        AsyncMock(
            return_value={
                "token_endpoint": "https://idp.example.com/oauth2/token",
                "issuer": "https://idp.example.com",
            },
        ),
    )
    app = _build_app(plugin, client_dependency)

    with pytest.raises(OAuthError, match="issuer mismatch"):
        TestClient(app).get(
            "/auth/provider/acme/callback?code=test-code&state=test-state&iss=https%3A%2F%2Fevil.example",
        )


def test_callback_redirects_to_error_url_on_oauth_failure(monkeypatch) -> None:
    plugin = _build_plugin()
    oauth_state = _build_state(error_redirect_url="/error")
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=SimpleNamespace(
            get_oauth_state=AsyncMock(return_value=oauth_state),
            delete_oauth_state=AsyncMock(return_value=True),
        ),
    )
    monkeypatch.setattr(
        plugin,
        "resolve_server_metadata",
        AsyncMock(return_value={"token_endpoint": "https://idp.example.com/oauth2/token"}),
    )
    monkeypatch.setattr(plugin, "exchange_code_for_tokens", AsyncMock(side_effect=OAuthError("bad token")))
    app = _build_app(plugin, client_dependency)

    response = TestClient(app).get(
        "/auth/provider/acme/callback?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=oauth_callback_failed"


def test_signin_disallows_signup_when_provider_forbids_it(monkeypatch) -> None:
    plugin = _build_plugin(allow_sign_up=False)
    oauth_state = _build_state(error_redirect_url="/error")
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=oauth_state),
        delete_oauth_state=AsyncMock(return_value=True),
        get_individual_by_email=AsyncMock(return_value=None),
        get_individual_by_id=AsyncMock(return_value=None),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=None),
        get_or_create_individual=AsyncMock(),
        sign_in_individual=AsyncMock(),
        after_sign_up=AsyncMock(),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )

    monkeypatch.setattr(
        plugin,
        "resolve_server_metadata",
        AsyncMock(return_value={"token_endpoint": "https://idp.example.com/oauth2/token"}),
    )
    monkeypatch.setattr(plugin, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
    monkeypatch.setattr(
        plugin,
        "_fetch_provider_profile",
        AsyncMock(
            return_value=OAuthUserInfo(
                provider_account_id="provider-account-1",
                email="new@example.com",
                email_verified=True,
                raw={"sub": "provider-account-1"},
            ),
        ),
    )

    app = _build_app(plugin, client_dependency)
    response = TestClient(app).get(
        "/auth/provider/acme/callback?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=oauth_callback_failed"
    client_dependency.get_or_create_individual.assert_not_awaited()


def test_signin_requires_explicit_signup_flag(monkeypatch) -> None:
    plugin = _build_plugin(require_explicit_sign_up=True)
    oauth_state = _build_state(error_redirect_url="/error", request_sign_up=False)
    adapter = SimpleNamespace(
        get_oauth_state=AsyncMock(return_value=oauth_state),
        delete_oauth_state=AsyncMock(return_value=True),
        get_individual_by_email=AsyncMock(return_value=None),
        get_individual_by_id=AsyncMock(return_value=None),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=None),
        get_or_create_individual=AsyncMock(),
        sign_in_individual=AsyncMock(),
        after_sign_up=AsyncMock(),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )

    monkeypatch.setattr(
        plugin,
        "resolve_server_metadata",
        AsyncMock(return_value={"token_endpoint": "https://idp.example.com/oauth2/token"}),
    )
    monkeypatch.setattr(plugin, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
    monkeypatch.setattr(
        plugin,
        "_fetch_provider_profile",
        AsyncMock(
            return_value=OAuthUserInfo(
                provider_account_id="provider-account-1",
                email="new@example.com",
                email_verified=True,
                raw={"sub": "provider-account-1"},
            ),
        ),
    )

    app = _build_app(plugin, client_dependency)
    response = TestClient(app).get(
        "/auth/provider/acme/callback?code=test-code&state=test-state",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=oauth_callback_failed"
    client_dependency.get_or_create_individual.assert_not_awaited()


@pytest.mark.asyncio
async def test_refresh_account_encrypts_tokens_at_rest() -> None:
    async def refresh_tokens(_oauth_client, account, _token_params):
        return {
            "access_token": "fresh-access-token",
            "refresh_token": account.refresh_token,
            "token_type": "Bearer",
            "scope": account.scope,
            "expires_in": 3600,
            "id_token": "fresh-id-token",
        }

    plugin = _build_plugin(encrypt_tokens=True, refresh_tokens=refresh_tokens)
    record = _build_account()

    async def update_oauth_account_by_id(_account_id, **updates: object):
        return _build_account(
            id=record.id,
            individual_id=record.individual_id,
            provider_account_id=record.provider_account_id,
            access_token=updates["access_token"],
            refresh_token=updates["refresh_token"],
            expires_at=updates["expires_at"].replace(tzinfo=None),
            token_type=updates["token_type"],
            scope=updates["scope"],
            id_token=updates["id_token"],
        )

    client_dependency = SimpleNamespace(
        get_oauth_account_for_individual=AsyncMock(return_value=record),
        update_oauth_account_by_id=AsyncMock(side_effect=update_oauth_account_by_id),
    )

    result = await plugin.refresh_account(
        client_dependency,
        individual_id=record.individual_id,
        provider_account_id=record.provider_account_id,
    )

    update_kwargs = client_dependency.update_oauth_account_by_id.await_args.kwargs
    assert update_kwargs["access_token"].startswith("enc:v1:")
    assert update_kwargs["refresh_token"].startswith("enc:v1:")
    assert update_kwargs["id_token"].startswith("enc:v1:")
    assert result.access_token == "fresh-access-token"  # noqa: S105
    assert result.id_token == "fresh-id-token"  # noqa: S105


@pytest.mark.asyncio
async def test_get_access_token_auto_refreshes_expired_tokens(monkeypatch) -> None:
    plugin = _build_plugin()
    expired = _linked_account(
        expires_at=datetime.now(UTC) - timedelta(seconds=10),
        access_token="expired-token",
    )
    refreshed = _linked_account(
        individual_id=expired.individual_id,
        provider_account_id=expired.provider_account_id,
        access_token="fresh-token",
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    monkeypatch.setattr(plugin, "_get_linked_account", AsyncMock(return_value=expired))
    monkeypatch.setattr(plugin, "refresh_account", AsyncMock(return_value=refreshed))

    token = await plugin.get_access_token(
        SimpleNamespace(),
        individual_id=expired.individual_id,
        provider_account_id=expired.provider_account_id,
    )

    assert token == "fresh-token"  # noqa: S105
    plugin.refresh_account.assert_awaited_once()


@pytest.mark.asyncio
async def test_account_info_fetches_provider_profile() -> None:
    async def get_userinfo(_oauth_client, _token_set, _metadata):
        return {
            "sub": "provider-account-9",
            "email": "profile@example.com",
            "email_verified": True,
            "name": "Profile Person",
            "picture": "https://example.com/avatar.jpg",
        }

    plugin = _build_plugin(get_userinfo=get_userinfo)
    record = _build_account(provider_account_id="provider-account-9")
    client_dependency = SimpleNamespace(get_oauth_account_for_individual=AsyncMock(return_value=record))

    profile = await plugin.account_info(
        client_dependency,
        individual_id=record.individual_id,
        provider_account_id=record.provider_account_id,
    )

    assert profile is not None
    assert profile.provider_account_id == "provider-account-9"
    assert profile.email == "profile@example.com"
    assert profile.email_verified is True


@pytest.mark.asyncio
async def test_unlink_account_uses_provider_account_id() -> None:
    plugin = _build_plugin()
    client_dependency = SimpleNamespace(unlink_oauth_account=AsyncMock(return_value=True))
    individual_id = uuid4()

    result = await plugin.unlink_account(
        client_dependency,
        individual_id=individual_id,
        provider_account_id="provider-account-1",
    )

    assert result is True
    client_dependency.unlink_oauth_account.assert_awaited_once_with(
        individual_id=individual_id,
        provider="acme",
        provider_account_id="provider-account-1",
    )


@pytest.mark.asyncio
async def test_list_accounts_supports_multiple_same_provider_accounts() -> None:
    plugin = _build_plugin()
    individual_id = uuid4()
    first = _build_account(individual_id=individual_id, provider_account_id="provider-account-1")
    second = _build_account(individual_id=individual_id, provider_account_id="provider-account-2")
    client_dependency = SimpleNamespace(list_oauth_accounts=AsyncMock(return_value=[first, second]))

    accounts = await plugin.list_accounts(client_dependency, individual_id=individual_id)

    assert [account.provider_account_id for account in accounts] == ["provider-account-1", "provider-account-2"]
