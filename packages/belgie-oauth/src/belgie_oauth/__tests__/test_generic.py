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
from belgie_core.core.settings import BelgieSettings, CookieSettings
from belgie_oauth import OAuthLinkedAccount, OAuthPlugin, OAuthProvider, OAuthTokenSet, OAuthUserInfo
from belgie_oauth.__tests__.helpers import build_jwks_document, build_rsa_signing_key, issue_id_token
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
    belgie_settings = BelgieSettings(
        secret="test-secret",
        base_url="http://localhost:8000",
        cookie=CookieSettings(secure=False, http_only=True, same_site="lax"),
    )
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
        "access_token_expires_at": datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=1),
        "refresh_token_expires_at": datetime.now(UTC).replace(tzinfo=None) + timedelta(days=30),
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


def _build_state_adapter(**overrides: object) -> SimpleNamespace:
    store: dict[str, SimpleNamespace] = {}

    async def create_oauth_state(_db, **kwargs: object) -> SimpleNamespace:
        state = SimpleNamespace(**kwargs)
        store[state.state] = state
        return state

    async def get_oauth_state(_db, state: str) -> SimpleNamespace | None:
        return store.get(state)

    async def delete_oauth_state(_db, state: str) -> bool:
        return store.pop(state, None) is not None

    data = {
        "create_oauth_state": AsyncMock(side_effect=create_oauth_state),
        "get_oauth_state": AsyncMock(side_effect=get_oauth_state),
        "delete_oauth_state": AsyncMock(side_effect=delete_oauth_state),
        "get_individual_by_email": AsyncMock(return_value=None),
        "get_individual_by_id": AsyncMock(return_value=None),
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _token_set(**overrides: object) -> OAuthTokenSet:
    data = {
        "access_token": "access-token",
        "token_type": "Bearer",
        "refresh_token": "refresh-token",
        "scope": "openid email profile",
        "id_token": "id-token",
        "access_token_expires_at": datetime.now(UTC) + timedelta(hours=1),
        "refresh_token_expires_at": datetime.now(UTC) + timedelta(days=30),
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
        "access_token_expires_at": datetime.now(UTC) + timedelta(hours=1),
        "refresh_token_expires_at": datetime.now(UTC) + timedelta(days=30),
        "token_type": "Bearer",
        "scope": "openid email profile",
        "id_token": None,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    data.update(overrides)
    return OAuthLinkedAccount(**data)


def _path_and_query(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path


def _start_provider_flow(test_client: TestClient, start_url: str) -> tuple[str, str]:
    response = test_client.get(_path_and_query(start_url), follow_redirects=False)
    assert response.status_code == 302
    provider_url = response.headers["location"]
    state = parse_qs(urlparse(provider_url).query)["state"][0]
    return provider_url, state


def _cookie_names(test_client: TestClient) -> set[str]:
    return {cookie.name for cookie in test_client.cookies.jar}


def test_provider_requires_discovery_or_manual_endpoints() -> None:
    with pytest.raises(ValidationError):
        OAuthProvider(
            provider_id="acme",
            client_id="client-id",
            client_secret=SecretStr("client-secret"),
        )


def test_provider_rejects_empty_client_id_list() -> None:
    with pytest.raises(ValidationError):
        OAuthProvider(
            provider_id="acme",
            client_id=[],
            client_secret=SecretStr("client-secret"),
            authorization_endpoint="https://idp.example.com/oauth2/authorize",
            token_endpoint="https://idp.example.com/oauth2/token",
        )


def test_dependency_requires_router_initialization() -> None:
    plugin = _build_plugin()

    with pytest.raises(RuntimeError, match=r"router initialization"):
        plugin()


@pytest.mark.asyncio
async def test_signin_url_uses_start_route_and_persists_adapter_state() -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)
    app = _build_app(plugin, client_dependency)

    start_url = await oauth_client.signin_url(
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
    assert urlparse(start_url).netloc == "localhost:8000"

    with TestClient(app) as test_client:
        provider_url, _ = _start_provider_flow(test_client, start_url)
        query = parse_qs(urlparse(provider_url).query)

    assert urlparse(provider_url).netloc == "idp.example.com"
    assert query["prompt"][0] == "consent"
    assert query["access_type"][0] == "offline"
    assert query["nonce"][0]
    assert query["code_challenge"][0]
    assert query["code_challenge_method"][0] == "S256"


@pytest.mark.asyncio
async def test_signin_url_uses_primary_client_id_from_list() -> None:
    plugin = _build_plugin(client_id=["primary-client-id", "secondary-client-id"])
    client_dependency = SimpleNamespace(db=object(), adapter=_build_state_adapter())
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)
    app = _build_app(plugin, client_dependency)

    start_url = await oauth_client.signin_url()

    with TestClient(app) as test_client:
        provider_url, _ = _start_provider_flow(test_client, start_url)
        query = parse_qs(urlparse(provider_url).query)

    assert query["client_id"][0] == "primary-client-id"


@pytest.mark.asyncio
async def test_link_url_persists_link_intent_and_individual() -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)
    app = _build_app(plugin, client_dependency)

    individual_id = uuid4()
    start_url = await oauth_client.link_url(
        individual_id=individual_id,
        return_to="/linked",
        payload={"flow": "link"},
    )

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

    with TestClient(app) as test_client:
        provider_url, _ = _start_provider_flow(test_client, start_url)

    assert provider_url.startswith("https://idp.example.com/oauth2/authorize")


@pytest.mark.asyncio
async def test_cookie_state_strategy_uses_cookie_store_and_trampoline() -> None:
    plugin = _build_plugin(state_strategy="cookie")
    adapter = _build_state_adapter()
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)
    app = _build_app(plugin, client_dependency)

    start_url = await oauth_client.signin_url(payload={"flow": "cookie"})

    adapter.create_oauth_state.assert_not_awaited()
    with TestClient(app) as test_client:
        provider_url, _ = _start_provider_flow(test_client, start_url)
        assert "belgie_oauth_acme_state" in _cookie_names(test_client)

    assert provider_url.startswith("https://idp.example.com/oauth2/authorize")


@pytest.mark.asyncio
async def test_signin_url_supports_additional_scope_reconsent() -> None:
    plugin = _build_plugin()
    client_dependency = SimpleNamespace(db=object(), adapter=_build_state_adapter())
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)
    app = _build_app(plugin, client_dependency)

    start_url = await oauth_client.signin_url(
        scopes=["openid", "email", "calendar.read"],
        prompt="select_account",
        payload={"scope": "expanded"},
    )

    with TestClient(app) as test_client:
        provider_url, _ = _start_provider_flow(test_client, start_url)
        query = parse_qs(urlparse(provider_url).query)

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
                "refresh_token_expires_in": 7200,
                "id_token": "test-id-token",
            },
        ),
    )

    token_set = await plugin.exchange_code_for_tokens("test-code", code_verifier="verifier")

    assert token_set.access_token == "new-access-token"  # noqa: S105
    assert token_set.refresh_token == "new-refresh-token"  # noqa: S105
    assert token_set.id_token == "test-id-token"  # noqa: S105
    assert token_set.access_token_expires_at is not None
    assert token_set.refresh_token_expires_at is not None


@pytest.mark.asyncio
@respx.mock
async def test_fetch_provider_profile_accepts_secondary_client_id_audience() -> None:
    plugin = _build_plugin(
        client_id=["primary-client-id", "secondary-client-id"],
        userinfo_endpoint=None,
        issuer="https://idp.example.com",
        jwks_uri="https://idp.example.com/jwks",
    )
    signing_key = build_rsa_signing_key(kid="multi-client-key")
    nonce = "multi-client-nonce"
    id_token = issue_id_token(
        signing_key=signing_key,
        issuer="https://idp.example.com",
        audience="secondary-client-id",
        subject="provider-account-1",
        nonce=nonce,
        claims={
            "email": "person@example.com",
            "email_verified": True,
            "name": "Test Person",
        },
    )

    respx.get("https://idp.example.com/jwks").mock(
        return_value=httpx.Response(200, json=build_jwks_document(signing_key)),
    )

    profile = await plugin._transport.fetch_provider_profile(
        OAuthTokenSet.from_response(
            {
                "access_token": "access-token",
                "token_type": "Bearer",
                "id_token": id_token,
                "expires_in": 3600,
            },
        ),
        nonce=nonce,
    )

    assert profile.provider_account_id == "provider-account-1"
    assert profile.email == "person@example.com"
    assert profile.email_verified is True


@pytest.mark.asyncio
async def test_callback_signin_new_user_exposes_payload_on_request_state(monkeypatch) -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
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
    app = _build_app(plugin, client_dependency)

    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)
    with TestClient(app) as test_client:
        # The trampoline sets the browser-bound state marker before the provider redirect.
        start_url = await oauth_client.signin_url(
            return_to="/after",
            error_redirect_url="/error",
            new_user_redirect_url="/welcome",
            payload={"flow": "signin"},
            request_sign_up=True,
        )
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(
            plugin._transport,
            "resolve_server_metadata",
            AsyncMock(return_value={"issuer": "https://idp.example.com"}),
        )
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
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
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}&iss=https%3A%2F%2Fidp.example.com",
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
        access_token_expires_at=ANY,
        refresh_token_expires_at=ANY,
        scope="openid email profile",
        token_type="Bearer",
        id_token="id-token",
    )

    request = app.state.belgie.after_authenticate.await_args.kwargs["request"]
    assert request.state.oauth_payload == {"flow": "signin"}
    assert request.state.oauth_state.intent == "signin"
    assert request.state.oauth_state.request_sign_up is True


@pytest.mark.asyncio
async def test_callback_link_flow_does_not_set_session_cookie(monkeypatch) -> None:
    plugin = _build_plugin()
    individual_id = uuid4()
    adapter = _build_state_adapter(
        get_individual_by_id=AsyncMock(return_value=SimpleNamespace(id=individual_id, email="linked@example.com")),
        update_individual=AsyncMock(),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=None),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )
    app = _build_app(plugin, client_dependency)

    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)
    with TestClient(app) as test_client:
        start_url = await oauth_client.link_url(
            individual_id=individual_id,
            return_to="/linked",
            payload={"flow": "link"},
        )
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-2",
                    email="linked@example.com",
                    email_verified=True,
                    raw={"sub": "provider-account-2"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
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
        access_token_expires_at=ANY,
        refresh_token_expires_at=ANY,
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


def test_adapter_state_rejects_missing_marker_cookie() -> None:
    plugin = _build_plugin()
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=SimpleNamespace(get_oauth_state=AsyncMock(return_value=_build_state())),
    )
    app = _build_app(plugin, client_dependency)

    with pytest.raises(InvalidStateError, match="marker"):
        TestClient(app).get("/auth/provider/acme/callback?code=test-code&state=test-state")


def test_cookie_state_rejects_missing_state_cookie() -> None:
    plugin = _build_plugin(state_strategy="cookie")
    client_dependency = SimpleNamespace(db=object(), adapter=SimpleNamespace())
    app = _build_app(plugin, client_dependency)

    with pytest.raises(InvalidStateError, match="state cookie"):
        TestClient(app).get("/auth/provider/acme/callback?code=test-code&state=test-state")


def test_cookie_state_form_post_normalizes_before_validation() -> None:
    plugin = _build_plugin(state_strategy="cookie", response_mode="form_post")
    client_dependency = SimpleNamespace(db=object(), adapter=SimpleNamespace())
    app = _build_app(plugin, client_dependency)

    response = TestClient(app).post(
        "/auth/provider/acme/callback",
        data={"code": "test-code", "state": "test-state", "iss": "https://idp.example.com"},
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert response.headers["location"].endswith(
        "/auth/provider/acme/callback?code=test-code&state=test-state&iss=https%3A%2F%2Fidp.example.com",
    )


@pytest.mark.asyncio
async def test_callback_rejects_issuer_mismatch(monkeypatch) -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url()
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(
            plugin._transport,
            "resolve_server_metadata",
            AsyncMock(return_value={"issuer": "https://idp.example.com"}),
        )
        with pytest.raises(OAuthError, match="issuer mismatch"):
            test_client.get(
                f"/auth/provider/acme/callback?code=test-code&state={state}&iss=https%3A%2F%2Fevil.example",
            )


@pytest.mark.asyncio
async def test_callback_redirects_to_error_url_on_oauth_failure(monkeypatch) -> None:
    plugin = _build_plugin()
    adapter = _build_state_adapter()
    client_dependency = SimpleNamespace(db=object(), adapter=adapter)
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url(error_redirect_url="/error")
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(
            plugin._transport,
            "exchange_code_for_tokens",
            AsyncMock(side_effect=OAuthError("bad token")),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=oauth_code_verification_failed"


@pytest.mark.asyncio
async def test_signin_disallows_signup_when_provider_forbids_it(monkeypatch) -> None:
    plugin = _build_plugin(disable_sign_up=True)
    adapter = _build_state_adapter()
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
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url(error_redirect_url="/error")
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="new@example.com",
                    email_verified=True,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=signup_disabled"
    client_dependency.get_or_create_individual.assert_not_awaited()


@pytest.mark.asyncio
async def test_signin_requires_explicit_signup_flag(monkeypatch) -> None:
    plugin = _build_plugin(disable_implicit_sign_up=True)
    adapter = _build_state_adapter()
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
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url(error_redirect_url="/error")
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="new@example.com",
                    email_verified=True,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=signup_disabled"
    client_dependency.get_or_create_individual.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_account_signin_can_skip_account_updates(monkeypatch) -> None:
    plugin = _build_plugin(update_account_on_sign_in=False)
    individual = SimpleNamespace(id=uuid4(), email="person@example.com")
    existing_account = _build_account(individual_id=individual.id, provider_account_id="provider-account-1")
    session = SimpleNamespace(id=uuid4())
    adapter = _build_state_adapter(
        get_individual_by_id=AsyncMock(return_value=individual),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=existing_account),
        sign_in_individual=AsyncMock(return_value=session),
        update_oauth_account_by_id=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url(return_to="/after")
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="person@example.com",
                    email_verified=False,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/after"
    client_dependency.update_oauth_account_by_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_signin_implicitly_links_existing_verified_user(monkeypatch) -> None:
    plugin = _build_plugin()
    individual = SimpleNamespace(id=uuid4(), email="person@example.com")
    session = SimpleNamespace(id=uuid4())
    adapter = _build_state_adapter(
        get_individual_by_email=AsyncMock(return_value=individual),
        update_individual=AsyncMock(return_value=individual),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=None),
        get_or_create_individual=AsyncMock(return_value=(individual, False)),
        sign_in_individual=AsyncMock(return_value=session),
        after_sign_up=AsyncMock(),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url()
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="person@example.com",
                    email_verified=True,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    client_dependency.upsert_oauth_account.assert_awaited_once_with(
        individual_id=individual.id,
        provider="acme",
        provider_account_id="provider-account-1",
        access_token="access-token",
        refresh_token="refresh-token",
        access_token_expires_at=ANY,
        refresh_token_expires_at=ANY,
        scope="openid email profile",
        token_type="Bearer",
        id_token="id-token",
    )


@pytest.mark.asyncio
async def test_signin_rejects_untrusted_implicit_linking(monkeypatch) -> None:
    plugin = _build_plugin()
    individual = SimpleNamespace(id=uuid4(), email="person@example.com")
    adapter = _build_state_adapter(
        get_individual_by_email=AsyncMock(return_value=individual),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=None),
        get_or_create_individual=AsyncMock(),
    )
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url(error_redirect_url="/error")
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="person@example.com",
                    email_verified=False,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=account_not_linked"
    client_dependency.get_or_create_individual.assert_not_awaited()


@pytest.mark.asyncio
async def test_signin_trusted_provider_can_implicitly_link_unverified_email(monkeypatch) -> None:
    plugin = _build_plugin(trusted_for_account_linking=True)
    individual = SimpleNamespace(id=uuid4(), email="person@example.com")
    session = SimpleNamespace(id=uuid4())
    adapter = _build_state_adapter(
        get_individual_by_email=AsyncMock(return_value=individual),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=None),
        get_or_create_individual=AsyncMock(return_value=(individual, False)),
        sign_in_individual=AsyncMock(return_value=session),
        after_sign_up=AsyncMock(),
        upsert_oauth_account=AsyncMock(),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url()
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="person@example.com",
                    email_verified=False,
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/dashboard"
    client_dependency.upsert_oauth_account.assert_awaited_once()


@pytest.mark.asyncio
async def test_link_flow_rejects_mismatched_email(monkeypatch) -> None:
    plugin = _build_plugin()
    individual_id = uuid4()
    adapter = _build_state_adapter(
        get_individual_by_id=AsyncMock(return_value=SimpleNamespace(id=individual_id, email="owner@example.com")),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=None),
        upsert_oauth_account=AsyncMock(),
    )
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.link_url(
            individual_id=individual_id,
            return_to="/linked",
            error_redirect_url="/error",
        )
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-2",
                    email="other@example.com",
                    email_verified=True,
                    raw={"sub": "provider-account-2"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=email_does_not_match"
    client_dependency.upsert_oauth_account.assert_not_awaited()


@pytest.mark.asyncio
async def test_link_flow_rejects_missing_email(monkeypatch) -> None:
    plugin = _build_plugin()
    individual_id = uuid4()
    adapter = _build_state_adapter(
        get_individual_by_id=AsyncMock(return_value=SimpleNamespace(id=individual_id, email="owner@example.com")),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=None),
        upsert_oauth_account=AsyncMock(),
    )
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.link_url(
            individual_id=individual_id,
            return_to="/linked",
            error_redirect_url="/error",
        )
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-2",
                    email=None,
                    email_verified=False,
                    raw={"sub": "provider-account-2"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "/error?error=email_missing"
    client_dependency.upsert_oauth_account.assert_not_awaited()


@pytest.mark.asyncio
async def test_email_verification_only_updates_when_provider_email_matches(monkeypatch) -> None:
    plugin = _build_plugin(override_user_info_on_sign_in=True)
    individual = SimpleNamespace(id=uuid4(), email="person@example.com")
    updated_individual = SimpleNamespace(id=individual.id, email=individual.email)
    existing_account = _build_account(individual_id=individual.id, provider_account_id="provider-account-1")
    session = SimpleNamespace(id=uuid4())
    adapter = _build_state_adapter(
        get_individual_by_id=AsyncMock(return_value=individual),
        update_individual=AsyncMock(return_value=updated_individual),
    )
    client_dependency = SimpleNamespace(
        db=object(),
        adapter=adapter,
        get_oauth_account=AsyncMock(return_value=existing_account),
        sign_in_individual=AsyncMock(return_value=session),
        update_oauth_account_by_id=AsyncMock(return_value=existing_account),
        create_session_cookie=MagicMock(side_effect=lambda _session, response: response),
    )
    app = _build_app(plugin, client_dependency)
    oauth_client = plugin._client_type(plugin=plugin, client=client_dependency)

    with TestClient(app) as test_client:
        start_url = await oauth_client.signin_url()
        _, state = _start_provider_flow(test_client, start_url)
        monkeypatch.setattr(plugin._transport, "resolve_server_metadata", AsyncMock(return_value={}))
        monkeypatch.setattr(plugin._transport, "exchange_code_for_tokens", AsyncMock(return_value=_token_set()))
        monkeypatch.setattr(
            plugin._transport,
            "fetch_provider_profile",
            AsyncMock(
                return_value=OAuthUserInfo(
                    provider_account_id="provider-account-1",
                    email="other@example.com",
                    email_verified=True,
                    name="Updated Name",
                    image="https://example.com/photo.jpg",
                    raw={"sub": "provider-account-1"},
                ),
            ),
        )
        response = test_client.get(
            f"/auth/provider/acme/callback?code=test-code&state={state}",
            follow_redirects=False,
        )

    assert response.status_code == 302
    update_kwargs = adapter.update_individual.await_args.kwargs
    assert update_kwargs["name"] == "Updated Name"
    assert update_kwargs["image"] == "https://example.com/photo.jpg"
    assert "email_verified_at" not in update_kwargs


@pytest.mark.asyncio
async def test_refresh_account_encrypts_tokens_and_persists_both_expiries() -> None:
    async def refresh_tokens(_oauth_client, token_set, _token_params):
        return {
            "access_token": "fresh-access-token",
            "refresh_token": token_set.refresh_token,
            "token_type": "Bearer",
            "scope": token_set.scope,
            "expires_in": 3600,
            "refresh_token_expires_in": 86400,
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
            access_token_expires_at=updates["access_token_expires_at"].replace(tzinfo=None),
            refresh_token_expires_at=updates["refresh_token_expires_at"].replace(tzinfo=None),
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
    assert update_kwargs["access_token_expires_at"] is not None
    assert update_kwargs["refresh_token_expires_at"] is not None
    assert result.access_token == "fresh-access-token"  # noqa: S105
    assert result.id_token == "fresh-id-token"  # noqa: S105


@pytest.mark.asyncio
async def test_token_set_and_get_access_token_auto_refresh_expired_tokens(monkeypatch) -> None:
    plugin = _build_plugin()
    oauth_client = plugin._client_type(plugin=plugin, client=SimpleNamespace())
    expired = _linked_account(
        access_token_expires_at=datetime.now(UTC) - timedelta(seconds=10),
        access_token="expired-token",
    )
    refreshed = _linked_account(
        individual_id=expired.individual_id,
        provider_account_id=expired.provider_account_id,
        access_token="fresh-token",
        access_token_expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    monkeypatch.setattr(plugin._flow, "_get_linked_account", AsyncMock(return_value=expired))
    monkeypatch.setattr(plugin._flow, "refresh_account", AsyncMock(return_value=refreshed))

    token_set = await oauth_client.token_set(
        individual_id=expired.individual_id,
        provider_account_id=expired.provider_account_id,
    )
    token = await oauth_client.get_access_token(
        individual_id=expired.individual_id,
        provider_account_id=expired.provider_account_id,
    )

    assert token_set.access_token == "fresh-token"  # noqa: S105
    assert token == "fresh-token"  # noqa: S105
    assert token_set.access_token_expires_at == refreshed.access_token_expires_at
    assert plugin._flow.refresh_account.await_count == 2


@pytest.mark.asyncio
async def test_account_info_fetches_provider_profile_with_custom_userinfo() -> None:
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
