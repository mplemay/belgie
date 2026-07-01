from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from types import TracebackType
from typing import TYPE_CHECKING, Final, Self, cast

from belgie import Environment, JsonOutput, Runtime, RuntimeOptions, RuntimePermissions, Script
from belgie.ext.core._options import BelgieOptions
from belgie.ext.core._run_code import SCRIPT_TIMEOUT_MESSAGE

if TYPE_CHECKING:
    from belgie._core import AsyncRuntime

DEFAULT_RUNTIME_OPTIONS: Final[RuntimeOptions] = RuntimeOptions(
    permissions=RuntimePermissions(allow_net=[]),
)
SESSION_NOT_ENTERED_MESSAGE: Final[str] = "Belgie runtime session must be entered before running scripts."

type AsyncExitArgs = tuple[
    type[BaseException] | None,
    BaseException | None,
    TracebackType | None,
]


@dataclass(kw_only=True)
class BelgieRuntimeSession(BelgieOptions):
    _exit_stack: AsyncExitStack | None = field(default=None, init=False, repr=False)
    _active_runtime: AsyncRuntime | None = field(default=None, init=False, repr=False)

    async def __aenter__(self) -> Self:
        if self._exit_stack is not None:
            return self

        stack = AsyncExitStack()
        try:
            self._active_runtime = await self._enter_runtime(stack)
            self._exit_stack = stack
        except BaseException:
            await stack.aclose()
            raise
        return self

    async def __aexit__(self, *args: object) -> bool | None:
        stack = self._exit_stack
        self._exit_stack = None
        self._active_runtime = None
        if stack is None:
            return None
        return await stack.__aexit__(*cast("AsyncExitArgs", args))

    async def run_script(self, source: str) -> JsonOutput:
        if self._active_runtime is None:
            raise RuntimeError(SESSION_NOT_ENTERED_MESSAGE)
        runner = self._active_runtime(Script(source))
        if self.timeout is None:
            return await runner()
        try:
            return await asyncio.wait_for(runner(), timeout=self.timeout)
        except TimeoutError as error:
            raise TimeoutError(SCRIPT_TIMEOUT_MESSAGE.format(timeout=self.timeout)) from error

    async def _enter_runtime(self, stack: AsyncExitStack) -> AsyncRuntime:
        if self.runtime is not None:
            return await stack.enter_async_context(self.runtime)

        options = self.runtime_options or DEFAULT_RUNTIME_OPTIONS
        if self.environment is None:
            active_environment = await stack.enter_async_context(Environment())
        elif isinstance(self.environment, Environment):
            active_environment = await stack.enter_async_context(self.environment)
        else:
            active_environment = self.environment

        return await stack.enter_async_context(Runtime(env=active_environment, options=options))
