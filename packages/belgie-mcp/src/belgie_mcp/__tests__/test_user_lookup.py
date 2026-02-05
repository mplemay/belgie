from __future__ import annotations

import base64
import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest

pytest.importorskip("mcp")

from belgie_mcp.user import get_user_from_access_token
from mcp.server.auth.middleware.auth_context import auth_context_var


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeUser:
    id: UUID
    email: str
    email_verified: bool
    name: str | None
    image: str | None
    created_at: datetime
    updated_at: datetime
    scopes: list[str] | None


class FakeAdapter:
    def __init__(self, user: FakeUser | None) -> None:
        self.user = user

    async def get_user_by_id(self, _session: object, user_id: UUID) -> FakeUser | None:
        if self.user and self.user.id == user_id:
            return self.user
        return None


@dataclass(frozen=True, slots=True, kw_only=True)
class FakeClient:
    adapter: FakeAdapter
    db: object


class FakeDBProvider:
    def __init__(self, db: object) -> None:
        self._db = db

    async def dependency(self):
        yield self._db


class FakeBelgie:
    def __init__(self, adapter: FakeAdapter, db_provider: FakeDBProvider) -> None:
        self.adapter = adapter
        self.db = db_provider

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


def _build_belgie(user: FakeUser | None) -> FakeBelgie:
    adapter = FakeAdapter(user)
    db = object()
    return FakeBelgie(adapter, FakeDBProvider(db))


@pytest.mark.asyncio
async def test_get_user_no_token_returns_none() -> None:
    belgie = _build_belgie(user=None)

    result = await get_user_from_access_token(belgie)

    assert result is None


@pytest.mark.asyncio
async def test_get_user_malformed_jwt_returns_none() -> None:
    belgie = _build_belgie(user=None)

    with _set_access_token("not-a-jwt"):
        result = await get_user_from_access_token(belgie)

    assert result is None


@pytest.mark.asyncio
async def test_get_user_missing_sub_returns_none() -> None:
    belgie = _build_belgie(user=None)
    token = _build_jwt({"iss": "issuer"})

    with _set_access_token(token):
        result = await get_user_from_access_token(belgie)

    assert result is None


@pytest.mark.asyncio
async def test_get_user_non_uuid_sub_returns_none() -> None:
    belgie = _build_belgie(user=None)
    token = _build_jwt({"sub": "not-a-uuid"})

    with _set_access_token(token):
        result = await get_user_from_access_token(belgie)

    assert result is None


@pytest.mark.asyncio
async def test_get_user_valid_sub_returns_user() -> None:
    user = FakeUser(
        id=uuid4(),
        email="user@example.com",
        email_verified=True,
        name="Test User",
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
