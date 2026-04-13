from __future__ import annotations

import base64
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid4

import pytest
from pydantic import AnyUrl

pytest.importorskip("mcp")

from belgie_core.core.settings import BelgieSettings
from belgie_mcp.user import get_user_from_access_token
from belgie_oauth_server.__tests__.helpers import build_oauth_settings
from belgie_oauth_server.models import OAuthServerClientMetadata
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.provider import AccessToken as OAuthServerAccessToken, AuthorizationParams, SimpleOAuthProvider
from belgie_oauth_server.testing import InMemoryDBConnection
from mcp.server.auth.middleware.auth_context import auth_context_var

if TYPE_CHECKING:
    from belgie_oauth_server.settings import OAuthServer


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeUser:
    id: UUID
    email: str
    email_verified_at: datetime | None
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[str]


class FakeAdapter:
    def __init__(self, user: FakeUser | None) -> None:
        self.user = user

    async def get_individual_by_id(self, _session: object, individual_id: UUID) -> FakeUser | None:
        if self.user and self.user.id == individual_id:
            return self.user
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeClient:
    adapter: FakeAdapter
    db: object


class FakeBelgie:
    def __init__(
        self,
        adapter: FakeAdapter,
        database: object,
        *,
        plugins: list[OAuthServerPlugin] | None = None,
    ) -> None:
        self.adapter = adapter
        self.database = database
        self.plugins = [] if plugins is None else plugins

    def __call__(self, db: object) -> FakeClient:
        return FakeClient(adapter=self.adapter, db=db)


@dataclass(frozen=True, slots=True, kw_only=True)
class DummyAccessToken:
    token: str


@dataclass(frozen=True, slots=True, kw_only=True)
class DummyAuthUser:
    access_token: DummyAccessToken


@contextmanager
def _set_access_token(value: str):
    auth_user = DummyAuthUser(access_token=DummyAccessToken(token=value))
    token = auth_context_var.set(auth_user)
    try:
        yield
    finally:
        auth_context_var.reset(token)


def _build_jwt(payload: dict[str, object]) -> str:
    header = _b64url({"alg": "none", "typ": "JWT"})
    body = _b64url(payload)
    return f"{header}.{body}.sig"


def _b64url(payload: dict[str, object]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _build_belgie(user: FakeUser | None, *, plugins: list[OAuthServerPlugin] | None = None) -> FakeBelgie:
    adapter = FakeAdapter(user)
    db = object()

    async def get_db():
        yield db

    return FakeBelgie(adapter, get_db, plugins=plugins)


@pytest.mark.asyncio
async def test_get_user_no_token_returns_none() -> None:
    belgie = _build_belgie(user=None)

    result = await get_user_from_access_token(belgie)

    assert result is None


@pytest.mark.asyncio
async def test_get_user_provider_backed_token_returns_user() -> None:
    user = FakeUser(
        id=uuid4(),
        email="user@example.com",
        email_verified_at=datetime.now(UTC),
        name="Test Individual",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=["user"],
    )
    oauth_plugin, provider = _build_oauth_plugin()
    token, _stored_token = await _issue_dynamic_client_access_token(provider, individual_id=str(user.id))
    belgie = _build_belgie(user=user, plugins=[oauth_plugin])

    with _set_access_token(token):
        result = await get_user_from_access_token(belgie)

    assert result is user


@pytest.mark.asyncio
async def test_get_user_provider_backed_token_returns_none_without_user_id() -> None:
    oauth_plugin, provider = _build_oauth_plugin()
    token, stored_token = await _issue_dynamic_client_access_token(provider, individual_id=str(uuid4()))
    _ = stored_token
    provider.adapter.access_tokens[provider._hash_value(token)].individual_id = None
    belgie = _build_belgie(user=None, plugins=[oauth_plugin])

    with _set_access_token(token):
        result = await get_user_from_access_token(belgie)

    assert result is None


@pytest.mark.asyncio
async def test_get_user_provider_backed_token_returns_none_for_invalid_user_id() -> None:
    oauth_plugin, provider = _build_oauth_plugin()
    token, stored_token = await _issue_dynamic_client_access_token(provider, individual_id=str(uuid4()))
    _ = stored_token
    provider.adapter.access_tokens[provider._hash_value(token)].individual_id = "not-a-uuid"  # type: ignore[assignment]
    belgie = _build_belgie(user=None, plugins=[oauth_plugin])

    with _set_access_token(token):
        result = await get_user_from_access_token(belgie)

    assert result is None


@pytest.mark.asyncio
async def test_get_user_provider_backed_token_returns_none_when_user_is_missing() -> None:
    oauth_plugin, provider = _build_oauth_plugin()
    token, _stored_token = await _issue_dynamic_client_access_token(provider, individual_id=str(uuid4()))
    belgie = _build_belgie(user=None, plugins=[oauth_plugin])

    with _set_access_token(token):
        result = await get_user_from_access_token(belgie)

    assert result is None


@pytest.mark.asyncio
async def test_get_user_malformed_jwt_returns_none() -> None:
    belgie = _build_belgie(user=None)

    with _set_access_token("not-a-jwt"):
        result = await get_user_from_access_token(belgie)

    assert result is None


@pytest.mark.asyncio
async def test_get_user_valid_sub_returns_user_when_no_provider_matches() -> None:
    user = FakeUser(
        id=uuid4(),
        email="user@example.com",
        email_verified_at=datetime.now(UTC),
        name="Test Individual",
        image=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        scopes=["user"],
    )
    belgie = _build_belgie(user=user)
    token = _build_jwt({"sub": str(user.id)})

    with _set_access_token(token):
        result = await get_user_from_access_token(belgie)

    assert result is user


def _oauth_settings() -> OAuthServer:
    return build_oauth_settings(
        base_url="https://issuer.local",
        redirect_uris=["http://localhost:6274/oauth/callback"],
        client_id="test-client",
        client_secret="test-secret",
        default_scope="user",
    )


def _build_oauth_plugin() -> tuple[OAuthServerPlugin, SimpleOAuthProvider]:
    settings = _oauth_settings()
    db = InMemoryDBConnection()
    provider = SimpleOAuthProvider(settings, issuer_url=str(settings.issuer_url), database_factory=lambda: db)
    plugin = OAuthServerPlugin(
        BelgieSettings(secret="test-secret", base_url="http://localhost:8000"),
        settings,
    )
    plugin._provider = provider
    return plugin, provider


async def _issue_dynamic_client_access_token(
    provider: SimpleOAuthProvider,
    *,
    individual_id: str | None = None,
) -> tuple[str, OAuthServerAccessToken]:
    client = await provider.register_client(
        OAuthServerClientMetadata(
            redirect_uris=[AnyUrl("http://localhost:6274/oauth/callback")],
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
            scope="user",
            token_endpoint_auth_method="none",
        ),
    )
    state = await provider.authorize(
        client,
        AuthorizationParams(
            state=None,
            scopes=["user"],
            code_challenge="test-challenge",
            redirect_uri=AnyUrl("http://localhost:6274/oauth/callback"),
            redirect_uri_provided_explicitly=True,
            individual_id=individual_id,
            session_id=str(uuid4()),
        ),
    )
    redirect = await provider.issue_authorization_code(state)
    code = parse_qs(urlparse(redirect).query)["code"][0]
    authorization_code = await provider.load_authorization_code(code)
    assert authorization_code is not None
    token_response = await provider.exchange_authorization_code(authorization_code)
    stored_token = await provider.load_access_token(token_response.access_token)
    assert stored_token is not None
    return token_response.access_token, stored_token
