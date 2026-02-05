from __future__ import annotations

import inspect
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from contextlib import AbstractAsyncContextManager, AbstractContextManager, AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from belgie_proto import DBConnection
else:  # pragma: no cover
    DBConnection = object

from belgie_proto import UserProtocol

HookEvent = Literal["on_signup", "on_signin", "on_signout", "on_delete"]


@dataclass(frozen=True, slots=True, kw_only=True)
class HookContext[UserT: UserProtocol]:
    user: UserT
    db: DBConnection


type HookFunc = Callable[[HookContext], None | Awaitable[None]]
type HookCtxMgr = Callable[[HookContext], AbstractContextManager[None] | AbstractAsyncContextManager[None]]
type HookHandler = HookFunc | HookCtxMgr


@dataclass(frozen=True, slots=True, kw_only=True)
class PreSignupContext:
    email: str
    db: DBConnection
    name: str | None = None
    image: str | None = None
    email_verified: bool = False


type PreSignupFunc = Callable[[PreSignupContext], None | Awaitable[None]]
type PreSignupCtxMgr = Callable[
    [PreSignupContext],
    AbstractContextManager[None] | AbstractAsyncContextManager[None],
]
type PreSignupHandler = PreSignupFunc | PreSignupCtxMgr


@dataclass(frozen=True, slots=True, kw_only=True)
class Hooks:
    on_before_signup: PreSignupHandler | Sequence[PreSignupHandler] | None = None
    on_signup: HookHandler | Sequence[HookHandler] | None = None
    on_signin: HookHandler | Sequence[HookHandler] | None = None
    on_signout: HookHandler | Sequence[HookHandler] | None = None
    on_delete: HookHandler | Sequence[HookHandler] | None = None


type DispatchResult = None | Awaitable[None] | AbstractContextManager[None] | AbstractAsyncContextManager[None]
type DispatchHandler[ContextT] = Callable[[ContextT], DispatchResult]


@dataclass(frozen=True, slots=True, kw_only=True)
class HookRunner:
    hooks: Hooks

    @asynccontextmanager
    async def dispatch(self, event: HookEvent | str, context: HookContext) -> AsyncIterator[None]:
        async with self._dispatch_handlers(self._handlers_for(event), context):
            yield

    @asynccontextmanager
    async def dispatch_pre_signup(self, context: PreSignupContext) -> AsyncIterator[None]:
        async with self._dispatch_handlers(self.hooks.on_before_signup, context):
            yield

    def _handlers_for(
        self,
        event: HookEvent | str,
    ) -> DispatchHandler[HookContext] | Sequence[DispatchHandler[HookContext]] | None:
        match event:
            case "on_signup":
                return self.hooks.on_signup
            case "on_signin":
                return self.hooks.on_signin
            case "on_signout":
                return self.hooks.on_signout
            case "on_delete":
                return self.hooks.on_delete
            case _:
                return None

    @asynccontextmanager
    async def _dispatch_handlers[ContextT](
        self,
        handlers: DispatchHandler[ContextT] | Sequence[DispatchHandler[ContextT]] | None,
        context: ContextT,
    ) -> AsyncIterator[None]:
        normalized = self._normalize(handlers)
        if not normalized:
            yield
            return

        async with AsyncExitStack() as stack:
            for handler in normalized:
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

    @staticmethod
    def _normalize[HandlerT](handlers: HandlerT | Sequence[HandlerT] | None) -> list[HandlerT]:
        if handlers is None:
            return []

        if isinstance(handlers, Sequence) and not isinstance(handlers, (str, bytes)):
            return list(handlers)

        return [handlers]
