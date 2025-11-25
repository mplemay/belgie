from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from belgie.auth.core.client import AuthClient
from belgie.auth.core.hooks import HookContext, HookRunner, Hooks
from belgie.auth.session.manager import SessionManager


@dataclass(slots=True)
class DummyUser:
    id: UUID
    email: str = "u@example.com"
    email_verified: bool = True
    name: str | None = None
    image: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    scopes: list[str] | None = None


@dataclass(slots=True)
class DummySession:
    id: UUID
    user_id: UUID
    expires_at: datetime
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class FakeAdapter:
    def __init__(self, user: DummyUser, session: DummySession) -> None:
        self._user = user
        self._session = session
        self.deleted_user = False

    async def get_user_by_id(self, _db, user_id):
        return self._user if user_id == self._user.id else None

    async def delete_user(self, _db, user_id):
        if user_id == self._user.id:
            self.deleted_user = True
            return True
        return False


class FakeSessionManager(SessionManager):
    def __init__(self, session) -> None:
        self._session = session

    async def get_session(self, _db, session_id):
        return self._session if session_id == self._session.id else None

    async def delete_session(self, _db, session_id):
        if session_id == self._session.id:
            self._session = None
            return True
        return False


class DummyDB:
    pass


@pytest.mark.asyncio
async def test_sign_out_dispatches_hook():
    user = DummyUser(id=uuid4())
    session = DummySession(id=uuid4(), user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=1))
    events: list[str] = []

    async def hook(ctx: HookContext) -> None:  # type: ignore[override]
        events.append(f"signout:{ctx.user.id}")

    client = AuthClient(
        db=DummyDB(),
        adapter=FakeAdapter(user, session),
        session_manager=FakeSessionManager(session),
        cookie_name="c",
        hook_runner=HookRunner(Hooks(on_signout=hook)),
    )

    assert await client.sign_out(session.id) is True
    assert events == [f"signout:{user.id}"]


@pytest.mark.asyncio
async def test_delete_user_dispatches_hook_before_delete():
    user = DummyUser(id=uuid4())
    session = DummySession(id=uuid4(), user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=1))
    adapter = FakeAdapter(user, session)
    events: list[str] = []

    async def hook(ctx: HookContext) -> None:  # type: ignore[override]
        events.append(f"delete:{ctx.user.id}")
        assert adapter.deleted_user is False

    client = AuthClient(
        db=DummyDB(),
        adapter=adapter,
        session_manager=FakeSessionManager(session),
        cookie_name="c",
        hook_runner=HookRunner(Hooks(on_delete=hook)),
    )

    assert await client.delete_user(user) is True
    assert events == [f"delete:{user.id}"]
    assert adapter.deleted_user is True
