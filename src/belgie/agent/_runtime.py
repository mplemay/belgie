from __future__ import annotations

import asyncio
import shutil
from contextlib import AsyncExitStack, suppress
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import TYPE_CHECKING, Final, Self, cast
from uuid import uuid4

from belgie import Command, Environment, JsonOutput, Runtime, RuntimeOptions, RuntimePermissions, Script
from belgie.agent._options import BelgieOptions
from belgie.agent._run_code import SCRIPT_TIMEOUT_MESSAGE

if TYPE_CHECKING:
    from belgie._core import AsyncRuntime

# Vite needs these; libc probing uses a sanitized process.report stub in @belgie/vite.
DEFAULT_VITE_SYS_PERMISSIONS: Final[tuple[str, ...]] = (
    "homedir",
    "uid",
    "gid",
    "cpus",
    "osRelease",
    "systemMemoryInfo",
)
SESSION_NOT_ENTERED_MESSAGE: Final[str] = "Belgie runtime session must be entered before running scripts."
RENDERING_UNAVAILABLE_MESSAGE: Final[str] = (
    "Widget rendering is unavailable: enable_rendering must be True on an owned session "
    "(custom `runtime=` does not provide a renderer)."
)
DEFAULT_RENDER_SPECIFIER: Final[str] = "npm:@belgie/vite"
DEFAULT_REACT_SPECIFIER: Final[str] = "npm:react@19.2.8"
DEFAULT_REACT_DOM_SPECIFIER: Final[str] = "npm:react-dom@19.2.8"

type AsyncExitArgs = tuple[
    type[BaseException] | None,
    BaseException | None,
    TracebackType | None,
]


def _script_runtime_options(root: Path) -> RuntimeOptions:
    return RuntimeOptions(
        permissions=RuntimePermissions(
            allow_read=[str(root)],
        ),
    )


def _render_runtime_options(root: Path) -> RuntimeOptions:
    return RuntimeOptions(
        permissions=RuntimePermissions(
            allow_env=[],
            allow_ffi=[str(root / "node_modules")],
            allow_net=["localhost"],
            allow_read=[str(root)],
            allow_sys=DEFAULT_VITE_SYS_PERMISSIONS,
            allow_write=[str(root)],
        ),
    )


def _temporary_workspace(stack: AsyncExitStack) -> Path:
    directory = stack.enter_context(TemporaryDirectory(prefix="belgie-agent-"))
    return Path(directory).resolve()


def _dependency_specifier(specifier: str) -> str:
    if specifier.startswith("npm:"):
        return specifier
    return f"npm:{specifier}"


def _package_name_from_specifier(specifier: str) -> str:
    rest = specifier.removeprefix("npm:")
    if rest.startswith("@"):
        slash = rest.find("/")
        if slash == -1:
            message = f"Could not parse scoped package name from {specifier!r}."
            raise ValueError(message)
        after_scope = rest[slash + 1 :]
        at = after_scope.find("@")
        if at == -1:
            return rest
        return rest[: slash + 1 + at]
    at = rest.find("@")
    if at == -1:
        return rest
    if at == 0:
        message = f"Could not parse package name from {specifier!r}."
        raise ValueError(message)
    return rest[:at]


def _render_dependencies(plugins: tuple[str, ...]) -> dict[str, str]:
    dependencies = {
        "@belgie/vite": DEFAULT_RENDER_SPECIFIER,
        "react": DEFAULT_REACT_SPECIFIER,
        "react-dom": DEFAULT_REACT_DOM_SPECIFIER,
    }
    for plugin in plugins:
        dependencies[_package_name_from_specifier(plugin)] = _dependency_specifier(plugin)
    return dependencies


async def _drain_cancelled_task(task: asyncio.Task[object]) -> None:
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
            return await self._active_runtime(Script(source))()
        task = asyncio.create_task(self._active_runtime(Script(source))())
        try:
            return await asyncio.wait_for(task, timeout=self.timeout)
        except TimeoutError as error:
            await _drain_cancelled_task(task)
            raise TimeoutError(SCRIPT_TIMEOUT_MESSAGE.format(timeout=self.timeout)) from error
        except asyncio.CancelledError:
            await _drain_cancelled_task(task)
            raise

    async def render_widget(self, source: str) -> str:
        if self._active_runtime is None:
            raise RuntimeError(SESSION_NOT_ENTERED_MESSAGE)
        render_runtime = self._render_runtime
        workspace = self._workspace
        if render_runtime is None or workspace is None or not self.enable_rendering:
            raise RuntimeError(RENDERING_UNAVAILABLE_MESSAGE)
        render_dir = workspace / f"render-{uuid4().hex}"
        render_dir.mkdir()
        widget_path = render_dir / "widget.tsx"
        out_path = render_dir / "widget.html"
        widget_path.write_text(source, encoding="utf-8")
        argv = ["--widget", str(widget_path), "--out", str(out_path)]
        for plugin in self.plugins:
            argv.extend(("--plugins", plugin))

        async def _build() -> None:
            await render_runtime(Command("@belgie/vite"))(*argv)

        try:
            if self.timeout is None:
                await _build()
            else:
                task = asyncio.create_task(_build())
                try:
                    await asyncio.wait_for(task, timeout=self.timeout)
                except TimeoutError as error:
                    await _drain_cancelled_task(task)
                    raise TimeoutError(SCRIPT_TIMEOUT_MESSAGE.format(timeout=self.timeout)) from error
                except asyncio.CancelledError:
                    await _drain_cancelled_task(task)
                    raise
            return out_path.read_text(encoding="utf-8")
        finally:
            shutil.rmtree(render_dir, ignore_errors=True)

    async def _enter_runtimes(self, stack: AsyncExitStack) -> tuple[AsyncRuntime, AsyncRuntime | None]:
        if self.runtime is not None:
            script_runtime = await stack.enter_async_context(self.runtime)
            return script_runtime, None

        if self.environment is None:
            root = _temporary_workspace(stack)
            dependencies = _render_dependencies(self.plugins) if self.enable_rendering else None
            active_environment = await stack.enter_async_context(
                Environment(dependencies, path=root),
            )
            if self.enable_rendering:
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
        if not self.enable_rendering:
            return script_runtime, None
        render_runtime = await stack.enter_async_context(
            Runtime(env=active_environment, options=_render_runtime_options(workspace)),
        )
        return script_runtime, render_runtime
