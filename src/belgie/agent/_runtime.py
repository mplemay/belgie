from __future__ import annotations

import asyncio
import sys
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import TYPE_CHECKING, Final, Self, cast

from belgie import Environment, JsonOutput, Runtime, RuntimeOptions, RuntimePermissions, Script
from belgie.agent._options import BelgieOptions
from belgie.agent._run_code import SCRIPT_TIMEOUT_MESSAGE

if TYPE_CHECKING:
    from belgie._core import AsyncRuntime

DEFAULT_VITE_SYS_PERMISSIONS: Final[tuple[str, ...]] = (
    "homedir",
    "uid",
    "gid",
    "cpus",
    "osRelease",
    "systemMemoryInfo",
)
# Linux native loaders (detect-libc / lightningcss / rolldown) probe these paths.
DEFAULT_VITE_READ_PATHS: Final[tuple[str, ...]] = (
    ()
    if sys.platform == "win32"
    else (
        "/etc",
        "/proc",
        "/usr/bin/ldd",
    )
)
SESSION_NOT_ENTERED_MESSAGE: Final[str] = "Belgie runtime session must be entered before running scripts."
DEFAULT_RENDER_SPECIFIER: Final[str] = "npm:@belgie/render"
INLINE_MODULE_FILENAME: Final[str] = "__deno_python_inline__.tsx"
RENDER_REQUEST_KEY: Final[str] = "__belgie_render_request__"
RENDER_DRIVER_SOURCE: Final[str] = """\
import { buildFromSource } from "@belgie/render/host";

export default function run(source: string, url: string) {
  return buildFromSource(source, url);
}
"""

type AsyncExitArgs = tuple[
    type[BaseException] | None,
    BaseException | None,
    TracebackType | None,
]


def _script_runtime_options(root: Path) -> RuntimeOptions:
    return RuntimeOptions(
        permissions=RuntimePermissions(
            allow_net=[],
            allow_read=[str(root)],
        ),
    )


def _render_runtime_options(root: Path) -> RuntimeOptions:
    return RuntimeOptions(
        permissions=RuntimePermissions(
            allow_ffi=[str(root / "node_modules")],
            allow_net=[],
            allow_read=[str(root), *DEFAULT_VITE_READ_PATHS],
            allow_sys=DEFAULT_VITE_SYS_PERMISSIONS,
            allow_write=[str(root)],
        ),
    )


def _temporary_workspace(stack: AsyncExitStack) -> Path:
    directory = stack.enter_context(TemporaryDirectory(prefix="belgie-agent-"))
    return Path(directory).resolve()


def is_render_request(value: object) -> bool:
    return isinstance(value, dict) and value.get(RENDER_REQUEST_KEY) == 1


async def _drain_cancelled_task(task: asyncio.Task[JsonOutput]) -> None:
    task.cancel()
    with suppress(BaseException):
        await task


@dataclass(kw_only=True)
class BelgieRuntimeSession(BelgieOptions):
    _exit_stack: AsyncExitStack | None = field(default=None, init=False, repr=False)
    _active_runtime: AsyncRuntime | None = field(default=None, init=False, repr=False)
    _render_runtime: AsyncRuntime | None = field(default=None, init=False, repr=False)
    _workspace: Path | None = field(default=None, init=False, repr=False)

    async def __aenter__(self) -> Self:
        if self._exit_stack is not None:
            return self

        stack = AsyncExitStack()
        try:
            self._active_runtime, self._render_runtime = await self._enter_runtimes(stack)
            self._exit_stack = stack
        except BaseException:
            await stack.aclose()
            raise
        return self

    async def __aexit__(self, *args: object) -> bool | None:
        stack = self._exit_stack
        self._exit_stack = None
        self._active_runtime = None
        self._render_runtime = None
        self._workspace = None
        if stack is None:
            return None
        return await stack.__aexit__(*cast("AsyncExitArgs", args))

    async def run_script(self, source: str) -> JsonOutput:
        if self._active_runtime is None:
            raise RuntimeError(SESSION_NOT_ENTERED_MESSAGE)
        if self.timeout is None:
            return await self._run_script(source)
        task = asyncio.create_task(self._run_script(source))
        try:
            return await asyncio.wait_for(task, timeout=self.timeout)
        except TimeoutError as error:
            await _drain_cancelled_task(task)
            raise TimeoutError(SCRIPT_TIMEOUT_MESSAGE.format(timeout=self.timeout)) from error
        except asyncio.CancelledError:
            await _drain_cancelled_task(task)
            raise

    async def _run_script(self, source: str) -> JsonOutput:
        runtime = self._active_runtime
        if runtime is None:
            raise RuntimeError(SESSION_NOT_ENTERED_MESSAGE)
        result = await runtime(Script(source))()
        if not is_render_request(result):
            return result
        return await self._render_html(source)

    async def _render_html(self, source: str) -> JsonOutput:
        if self._render_runtime is None or self._workspace is None:
            msg = (
                "@belgie/render requested HTML, but this session has no renderer side-channel "
                "(custom `runtime=` does not mediate rendering)."
            )
            raise RuntimeError(msg)
        url = (self._workspace / INLINE_MODULE_FILENAME).resolve().as_uri()
        return await self._render_runtime(Script(RENDER_DRIVER_SOURCE))(source, url)

    async def _enter_runtimes(self, stack: AsyncExitStack) -> tuple[AsyncRuntime, AsyncRuntime | None]:
        if self.runtime is not None:
            script_runtime = await stack.enter_async_context(self.runtime)
            return script_runtime, None

        if self.environment is None:
            root = _temporary_workspace(stack)
            active_environment = await stack.enter_async_context(
                Environment({"@belgie/render": DEFAULT_RENDER_SPECIFIER}, path=root),
            )
            await active_environment.install()
        elif isinstance(self.environment, Environment):
            active_environment = await stack.enter_async_context(self.environment)
        else:
            active_environment = self.environment

        workspace = Path(active_environment.workspace)
        self._workspace = workspace
        script_options = self.runtime_options or _script_runtime_options(workspace)
        script_runtime = await stack.enter_async_context(
            Runtime(env=active_environment, options=script_options),
        )
        render_runtime = await stack.enter_async_context(
            Runtime(env=active_environment, options=_render_runtime_options(workspace)),
        )
        return script_runtime, render_runtime
