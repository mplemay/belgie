import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

import pytest
from belgie_core.core.hooks import HookContext, HookRunner, Hooks


@dataclass(slots=True)
class DummyUser:
    id: str = "u"
    email: str = "u@example.com"
    email_verified: bool = True
    name: str | None = None
    image: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    scopes: list[str] | None = None


class DummyDB:
    pass


@pytest.mark.asyncio
async def test_sync_hook_runs_before_body():
    events: list[str] = []

    def hook(ctx: HookContext) -> None:  # type: ignore[override]
        events.append(f"hook:{ctx.user.id}")

    runner = HookRunner(hooks=Hooks(on_signin=hook))
    ctx = HookContext(user=DummyUser(id=str(uuid4())), db=DummyDB())

    async with runner.dispatch("on_signin", ctx):
        events.append("body")

    assert events == [f"hook:{ctx.user.id}", "body"]


@pytest.mark.asyncio
async def test_context_manager_hook_wraps_body():
    events: list[str] = []

    @asynccontextmanager
    async def hook(ctx: HookContext):  # type: ignore[override]
        events.append(f"enter:{ctx.user.id}")
        try:
            yield
        finally:
            events.append(f"exit:{ctx.user.id}")

    runner = HookRunner(hooks=Hooks(on_signout=hook))
    ctx = HookContext(user=DummyUser(id=str(uuid4())), db=DummyDB())

    async with runner.dispatch("on_signout", ctx):
        events.append("body")

    assert events == [f"enter:{ctx.user.id}", "body", f"exit:{ctx.user.id}"]


@pytest.mark.asyncio
async def test_async_hook_waits_before_body():
    events: list[str] = []

    async def hook(ctx: HookContext) -> None:  # type: ignore[override]
        await asyncio.sleep(0)
        events.append(f"async:{ctx.user.id}")

    runner = HookRunner(hooks=Hooks(on_signup=[hook]))
    ctx = HookContext(user=DummyUser(id=str(uuid4())), db=DummyDB())

    async with runner.dispatch("on_signup", ctx):
        events.append("body")

    assert events == [f"async:{ctx.user.id}", "body"]
