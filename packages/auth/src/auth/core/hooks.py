from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, AbstractContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, cast

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession
else:  # pragma: no cover
    AsyncSession = object

from auth.adapters.protocols import UserProtocol

HookEvent = Literal["on_signup", "on_signin", "on_signout", "on_delete"]


@dataclass(frozen=True, slots=True, kw_only=True)
class HookContext[UserT: UserProtocol]:
    user: UserT
    db: AsyncSession


type HookFunc = Callable[[HookContext], None | Awaitable[None]]
type HookCtxMgr = Callable[[HookContext], AbstractContextManager[None] | AbstractAsyncContextManager[None]]
type HookHandler = HookFunc | HookCtxMgr


@dataclass(frozen=True, slots=True, kw_only=True)
class Hooks:
    on_signup: HookHandler | Sequence[HookHandler] | None = None
    on_signin: HookHandler | Sequence[HookHandler] | None = None
    on_signout: HookHandler | Sequence[HookHandler] | None = None
    on_delete: HookHandler | Sequence[HookHandler] | None = None


class HookRunner:
    def __init__(self, hooks: Hooks) -> None:
        self._hooks = hooks

    @asynccontextmanager
    async def dispatch(self, event: HookEvent | str, context: HookContext) -> AsyncIterator[None]:
        handlers = self._normalize(self._handlers_for(event))

        if not handlers:
            yield
            return

        async with AsyncExitStack() as stack:
            for handler in handlers:
                result = handler(context)

                if hasattr(result, "__aenter__") and hasattr(result, "__aexit__"):
                    await stack.enter_async_context(result)  # type: ignore[arg-type]
                    continue

                if hasattr(result, "__enter__") and hasattr(result, "__exit__"):
                    stack.enter_context(result)  # type: ignore[arg-type]
                    continue

                if inspect.isawaitable(result):
                    await result

            yield

    def _handlers_for(self, event: HookEvent | str) -> HookHandler | Sequence[HookHandler] | None:
        match event:
            case "on_signup":
                return self._hooks.on_signup
            case "on_signin":
                return self._hooks.on_signin
            case "on_signout":
                return self._hooks.on_signout
            case "on_delete":
                return self._hooks.on_delete
            case _:
                return None

    def _normalize(self, handlers: HookHandler | Sequence[HookHandler] | None) -> list[HookHandler]:
        if handlers is None:
            return []

        if isinstance(handlers, Sequence) and not isinstance(handlers, (str, bytes)):
            return list(cast("Sequence[HookHandler]", handlers))

        return [cast("HookHandler", handlers)]
