from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from belgie_core.core.client import BelgieClient
from belgie_core.core.hooks import HookContext, HookRunner, Hooks, PreSignupContext
from belgie_core.core.settings import CookieSettings
from belgie_core.session.manager import SessionManager


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
        self.max_age = 3600

    async def get_session(self, _db, session_id):
        return self._session if session_id == self._session.id else None

    async def delete_session(self, _db, session_id):
        if session_id == self._session.id:
            self._session = None
            return True
        return False


class SignUpAdapter:
    def __init__(self, user: DummyUser | None = None) -> None:
        self._user = user
        self.created = False

    async def get_user_by_email(self, _db, email):
        return self._user if self._user and self._user.email == email else None

    async def create_user(self, _db, email, name=None, image=None, *, email_verified=False):
        self._user = DummyUser(
            id=uuid4(),
            email=email,
            email_verified=email_verified,
            name=name,
            image=image,
        )
        self.created = True
        return self._user


class SignUpSessionManager:
    def __init__(self, events: list[str], max_age: int = 3600) -> None:
        self._events = events
        self.max_age = max_age

    async def create_session(self, _db, user_id, ip_address=None, user_agent=None):
        self._events.append("session")
        return DummySession(
            id=uuid4(),
            user_id=user_id,
            expires_at=datetime.now(UTC) + timedelta(days=1),
            ip_address=ip_address,
            user_agent=user_agent,
        )


class DummyDB:
    pass


@pytest.mark.asyncio
async def test_sign_out_dispatches_hook():
    user = DummyUser(id=uuid4())
    session = DummySession(id=uuid4(), user_id=user.id, expires_at=datetime.now(UTC) + timedelta(days=1))
    events: list[str] = []

    async def hook(ctx: HookContext) -> None:  # type: ignore[override]
        events.append(f"signout:{ctx.user.id}")

    client = BelgieClient(
        db=DummyDB(),
        adapter=FakeAdapter(user, session),
        session_manager=FakeSessionManager(session),
        cookie_settings=CookieSettings(name="c"),
        hook_runner=HookRunner(hooks=Hooks(on_signout=hook)),
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

    client = BelgieClient(
        db=DummyDB(),
        adapter=adapter,
        session_manager=FakeSessionManager(session),
        cookie_settings=CookieSettings(name="c"),
        hook_runner=HookRunner(hooks=Hooks(on_delete=hook)),
    )

    assert await client.delete_user(user) is True
    assert events == [f"delete:{user.id}"]
    assert adapter.deleted_user is True


@pytest.mark.asyncio
async def test_sign_up_dispatches_hooks_in_order_for_new_user():
    events: list[str] = []
    adapter = SignUpAdapter()
    session_manager = SignUpSessionManager(events)

    async def on_before_signup(ctx: PreSignupContext) -> None:
        events.append(f"before_signup:{ctx.email}")

    async def on_signup(ctx: HookContext) -> None:  # type: ignore[override]
        events.append(f"signup:{ctx.user.id}")

    async def on_signin(ctx: HookContext) -> None:  # type: ignore[override]
        events.append(f"signin:{ctx.user.id}")

    client = BelgieClient(
        db=DummyDB(),
        adapter=adapter,
        session_manager=session_manager,
        cookie_settings=CookieSettings(name="c"),
        hook_runner=HookRunner(
            hooks=Hooks(
                on_before_signup=on_before_signup,
                on_signup=on_signup,
                on_signin=on_signin,
            ),
        ),
    )

    user, _session = await client.sign_up(
        "new@example.com",
    )

    assert events == [
        "before_signup:new@example.com",
        f"signup:{user.id}",
        "session",
        f"signin:{user.id}",
    ]


@pytest.mark.asyncio
async def test_sign_up_existing_user_skips_signup_hook():
    events: list[str] = []
    existing_user = DummyUser(id=uuid4(), email="existing@example.com")
    adapter = SignUpAdapter(existing_user)
    session_manager = SignUpSessionManager(events)

    async def on_signup(ctx: HookContext) -> None:  # type: ignore[override]
        events.append(f"signup:{ctx.user.id}")

    async def on_signin(ctx: HookContext) -> None:  # type: ignore[override]
        events.append(f"signin:{ctx.user.id}")

    client = BelgieClient(
        db=DummyDB(),
        adapter=adapter,
        session_manager=session_manager,
        cookie_settings=CookieSettings(name="c"),
        hook_runner=HookRunner(hooks=Hooks(on_signup=on_signup, on_signin=on_signin)),
    )

    user, _session = await client.sign_up(
        "existing@example.com",
    )

    assert user.id == existing_user.id
    assert events == ["session", f"signin:{existing_user.id}"]


@pytest.mark.asyncio
async def test_sign_up_can_be_blocked_before_writing_to_db():
    adapter = SignUpAdapter()
    session_events: list[str] = []
    session_manager = SignUpSessionManager(session_events)

    async def on_before_signup(ctx: PreSignupContext) -> None:
        if not ctx.email.endswith("@example.com"):
            msg = "email domain is not allowed"
            raise PermissionError(msg)

    client = BelgieClient(
        db=DummyDB(),
        adapter=adapter,
        session_manager=session_manager,
        cookie_settings=CookieSettings(name="c"),
        hook_runner=HookRunner(hooks=Hooks(on_before_signup=on_before_signup)),
    )

    with pytest.raises(PermissionError, match="email domain is not allowed"):
        await client.sign_up("blocked@other.com")

    assert adapter.created is False
    assert session_events == []
