from __future__ import annotations

import asyncio
import importlib
import math
from collections.abc import Callable, Coroutine, Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from types import TracebackType
from typing import Final, Protocol, Self, TypeGuard, runtime_checkable

import anyio

DEFAULT_TIMEOUT: Final[float] = 30.0
DEFAULT_MAX_OLD_GENERATION_SIZE_MB: Final[int] = 128
DEFAULT_RENDER_SPECIFIER: Final[str] = "npm:@belgie/render"
DEFAULT_RENDER_DEPENDENCIES: Final[dict[str, str]] = {
    "@belgie/render": DEFAULT_RENDER_SPECIFIER,
    "react": "npm:react@19.2.8",
    "react-dom": "npm:react-dom@19.2.8",
}
INLINE_MODULE_FILENAME: Final[str] = "__deno_python_inline__.tsx"
RENDER_HOST_ENTRY: Final[str] = "node_modules/@belgie/render/dist/host.js"
RENDER_REQUEST_KEY: Final[str] = "__belgie_render_request__"
DEFAULT_VITE_SYS_PERMISSIONS: Final[tuple[str, ...]] = (
    "homedir",
    "uid",
    "gid",
    "cpus",
    "osRelease",
    "systemMemoryInfo",
)
MISSING_BELGIE: Final[str] = (
    "Belgie Sandbox requires Belgie and Python 3.12-3.14. "
    'Install it with `uv add "belgie[pydantic-ai]"`.'
)

type JsonPrimitive = None | bool | int | float | str
type JsonOutput = JsonPrimitive | list["JsonOutput"] | dict[str, "JsonOutput"]


class _EnvironmentOptionsFactory(Protocol):
    def __call__(self, *, allow_remote: bool, no_npm: bool) -> object: ...


class _RuntimePermissionsFactory(Protocol):
    def __call__(
        self,
        *,
        allow_read: Sequence[str] | None = None,
        allow_net: Sequence[str] | None = None,
        allow_ffi: Sequence[str] | None = None,
        allow_sys: Sequence[str] | None = None,
        allow_write: Sequence[str] | None = None,
    ) -> object: ...


class _RuntimeOptionsFactory(Protocol):
    def __call__(self, *, max_old_generation_size_mb: int | None, permissions: object) -> object: ...


@runtime_checkable
class _ActiveEnvironment(Protocol):
    async def install(self) -> object: ...

    @property
    def workspace(self) -> Path: ...


class _EnvironmentContext(Protocol):
    async def __aenter__(self) -> object: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class _EnvironmentFactory(Protocol):
    def __call__(
        self,
        dependencies: Mapping[str, str] | None = None,
        *,
        path: str | Path | None = None,
        options: object | None = None,
    ) -> _EnvironmentContext: ...


class _RuntimeContext(Protocol):
    async def __aenter__(self) -> object: ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...


class _RuntimeFactory(Protocol):
    def __call__(self, *, env: object | None = None, options: object | None = None) -> _RuntimeContext: ...


class _ScriptInstance(Protocol):
    pass


class _ScriptFactory(Protocol):
    def __call__(self, content: str) -> _ScriptInstance: ...

    def from_file(self, path: str | Path) -> _ScriptInstance: ...


@runtime_checkable
class _AsyncRuntime(Protocol):
    def __call__(self, target: object) -> Callable[..., Coroutine[object, object, JsonOutput]]: ...


@runtime_checkable
class _BelgieModule(Protocol):
    Environment: _EnvironmentFactory
    EnvironmentOptions: _EnvironmentOptionsFactory
    Runtime: _RuntimeFactory
    RuntimeOptions: _RuntimeOptionsFactory
    RuntimePermissions: _RuntimePermissionsFactory
    Script: _ScriptFactory


@runtime_checkable
class _BelgieErrorsModule(Protocol):
    BelgieError: type[Exception]


def _load_belgie() -> _BelgieModule:
    try:
        module = importlib.import_module("belgie")
    except ImportError as error:
        raise BelgieSandboxUnavailableError(MISSING_BELGIE) from error
    if not isinstance(module, _BelgieModule):
        raise BelgieSandboxUnavailableError("The installed Belgie package does not provide the required runtime API.")
    return module


def _load_belgie_error() -> type[Exception]:
    try:
        module = importlib.import_module("belgie.errors")
    except ImportError as error:
        raise BelgieSandboxUnavailableError(MISSING_BELGIE) from error
    if not isinstance(module, _BelgieErrorsModule):
        raise BelgieSandboxUnavailableError("The installed Belgie package does not provide its public error API.")
    return module.BelgieError


def _is_json_object(value: object) -> TypeGuard[dict[str, object]]:
    return type(value) is dict


def is_render_request(value: object) -> bool:
    if not _is_json_object(value):
        return False
    marker = value.get(RENDER_REQUEST_KEY)
    return type(marker) is int and marker == 1


class BelgieSandboxError(RuntimeError):
    pass


class BelgieSandboxExecutionError(BelgieSandboxError):
    pass


class BelgieSandboxTimeoutError(BelgieSandboxExecutionError):
    pass


class BelgieSandboxUnavailableError(BelgieSandboxError):
    pass


async def _drain_cancelled_task(task: asyncio.Task[JsonOutput]) -> None:
    task.cancel()
    with suppress(BaseException):
        await task


class BelgieSandboxSession:
    def __init__(
        self,
        *,
        allow_package_imports: bool = False,
        allow_network: bool = False,
        enable_rendering: bool = False,
        max_old_generation_size_mb: int | None = DEFAULT_MAX_OLD_GENERATION_SIZE_MB,
        runtime: _RuntimeContext | None = None,
    ) -> None:
        for name, value in (
            ("allow_package_imports", allow_package_imports),
            ("allow_network", allow_network),
            ("enable_rendering", enable_rendering),
        ):
            if type(value) is not bool:
                raise ValueError(f"{name} must be a bool, got {value!r}.")
        if max_old_generation_size_mb is not None and (
            type(max_old_generation_size_mb) is not int or max_old_generation_size_mb <= 0
        ):
            raise ValueError(
                "max_old_generation_size_mb must be a positive integer or None, "
                f"got {max_old_generation_size_mb!r}."
            )
        if runtime is not None:
            conflicts = [
                name
                for name, value, default in (
                    ("allow_package_imports", allow_package_imports, False),
                    ("allow_network", allow_network, False),
                    ("enable_rendering", enable_rendering, False),
                    (
                        "max_old_generation_size_mb",
                        max_old_generation_size_mb,
                        DEFAULT_MAX_OLD_GENERATION_SIZE_MB,
                    ),
                )
                if value != default
            ]
            if conflicts:
                raise ValueError(
                    f"{', '.join(conflicts)} cannot be combined with `runtime`, which already defines "
                    "the Belgie environment and runtime options."
                )
        self._allow_package_imports = allow_package_imports
        self._allow_network = allow_network
        self._enable_rendering = enable_rendering
        self._max_old_generation_size_mb = max_old_generation_size_mb
        self._configured_runtime = runtime
        self._entering = False
        self._runtime_context: _RuntimeContext | None = None
        self._render_runtime_context: _RuntimeContext | None = None
        self._environment_context: _EnvironmentContext | None = None
        self._temporary_directory: TemporaryDirectory[str] | None = None
        self._active_runtime: _AsyncRuntime | None = None
        self._render_runtime: _AsyncRuntime | None = None
        self._render_script: object | None = None
        self._workspace: Path | None = None

    @property
    def is_open(self) -> bool:
        return self._active_runtime is not None

    @property
    def workspace(self) -> Path | None:
        return self._workspace

    async def __aenter__(self) -> Self:
        if self._entering or any(
            resource is not None
            for resource in (
                self._runtime_context,
                self._render_runtime_context,
                self._environment_context,
                self._temporary_directory,
            )
        ):
            raise BelgieSandboxError(
                "The session is already open or has pending cleanup; close it before entering again. "
                "Use a separate session per concurrent context."
            )
        self._entering = True
        try:
            try:
                asyncio.get_running_loop()
            except RuntimeError as error:
                raise BelgieSandboxError("Belgie Sandbox requires an asyncio event loop.") from error
            belgie = _load_belgie()
            try:
                if self._configured_runtime is not None:
                    runtime_context = self._configured_runtime
                    active_runtime = await runtime_context.__aenter__()
                    self._runtime_context = runtime_context
                    if not isinstance(active_runtime, _AsyncRuntime):
                        raise BelgieSandboxUnavailableError(
                            "The installed Belgie package returned an incompatible runtime."
                        )
                    self._active_runtime = active_runtime
                else:
                    temporary_directory = TemporaryDirectory(prefix="belgie-sandbox-")
                    self._temporary_directory = temporary_directory
                    workspace = Path(temporary_directory.name).resolve()
                    self._workspace = workspace
                    packages_enabled = self._allow_package_imports or self._enable_rendering
                    dependencies = dict(DEFAULT_RENDER_DEPENDENCIES) if self._enable_rendering else None
                    environment_context = belgie.Environment(
                        dependencies,
                        path=workspace,
                        options=belgie.EnvironmentOptions(
                            allow_remote=packages_enabled,
                            no_npm=not packages_enabled,
                        ),
                    )
                    active_environment = await environment_context.__aenter__()
                    self._environment_context = environment_context
                    if not isinstance(active_environment, _ActiveEnvironment):
                        raise BelgieSandboxUnavailableError(
                            "The installed Belgie package returned an incompatible environment."
                        )
                    if self._enable_rendering:
                        await active_environment.install()
                    script_runtime_context = belgie.Runtime(
                        env=active_environment,
                        options=belgie.RuntimeOptions(
                            max_old_generation_size_mb=self._max_old_generation_size_mb,
                            permissions=belgie.RuntimePermissions(
                                allow_read=[str(workspace)],
                                allow_net=[] if self._allow_network else None,
                            ),
                        ),
                    )
                    active_runtime = await script_runtime_context.__aenter__()
                    self._runtime_context = script_runtime_context
                    if not isinstance(active_runtime, _AsyncRuntime):
                        raise BelgieSandboxUnavailableError(
                            "The installed Belgie package returned an incompatible runtime."
                        )
                    self._active_runtime = active_runtime
                    if self._enable_rendering:
                        render_runtime_context = belgie.Runtime(
                            env=active_environment,
                            options=belgie.RuntimeOptions(
                                max_old_generation_size_mb=self._max_old_generation_size_mb,
                                permissions=belgie.RuntimePermissions(
                                    allow_ffi=[str(workspace / "node_modules")],
                                    allow_net=["localhost"],
                                    allow_read=[str(workspace)],
                                    allow_sys=DEFAULT_VITE_SYS_PERMISSIONS,
                                    allow_write=[str(workspace)],
                                ),
                            ),
                        )
                        render_runtime = await render_runtime_context.__aenter__()
                        self._render_runtime_context = render_runtime_context
                        if not isinstance(render_runtime, _AsyncRuntime):
                            raise BelgieSandboxUnavailableError(
                                "The installed Belgie package returned an incompatible renderer runtime."
                            )
                        self._render_runtime = render_runtime
            except BaseException as error:
                try:
                    await self._close_resources(None, None, None)
                except BaseException as cleanup_error:
                    if isinstance(error, Exception):
                        raise BelgieSandboxUnavailableError(
                            f"Could not start the Belgie sandbox: {error}. Cleanup also failed: {cleanup_error}"
                        ) from error
                    raise error from cleanup_error
                if isinstance(error, Exception):
                    raise BelgieSandboxUnavailableError(f"Could not start the Belgie sandbox: {error}") from error
                raise
            return self
        finally:
            self._entering = False

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self._close_resources(exc_type, exc, traceback)

    async def _close_resources(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        first_error: BaseException | None = None
        with anyio.CancelScope(shield=True):
            render_runtime_context = self._render_runtime_context
            if render_runtime_context is not None:
                try:
                    await render_runtime_context.__aexit__(exc_type, exc, traceback)
                except BaseException as error:
                    first_error = first_error or error
                else:
                    self._render_runtime_context = None
                    self._render_runtime = None
                    self._render_script = None
            runtime_context = self._runtime_context
            if runtime_context is not None:
                try:
                    await runtime_context.__aexit__(exc_type, exc, traceback)
                except BaseException as error:
                    first_error = first_error or error
                else:
                    self._runtime_context = None
                    self._active_runtime = None
            environment_context = self._environment_context
            if environment_context is not None:
                try:
                    await environment_context.__aexit__(exc_type, exc, traceback)
                except BaseException as error:
                    first_error = first_error or error
                else:
                    self._environment_context = None
            temporary_directory = self._temporary_directory
            if temporary_directory is not None:
                try:
                    temporary_directory.cleanup()
                except BaseException as error:
                    first_error = first_error or error
                else:
                    self._temporary_directory = None
                    self._workspace = None

        self._entering = False
        if first_error is not None:
            raise first_error

    async def close(self) -> None:
        await self.__aexit__(None, None, None)

    async def run_script(self, source: str, *, timeout: float = DEFAULT_TIMEOUT) -> JsonOutput:
        active_runtime = self._active_runtime
        if active_runtime is None:
            raise BelgieSandboxError("The Belgie sandbox session is not open.")
        if type(source) is not str:
            raise TypeError(f"source must be a string, got {type(source).__name__}.")
        if type(timeout) is bool or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError(f"timeout must be a positive finite number, got {timeout!r}.")
        belgie = _load_belgie()
        belgie_error = _load_belgie_error()
        try:
            script = belgie.Script(source)
            task = asyncio.create_task(self._run_script(active_runtime, belgie, script, source))
            try:
                return await asyncio.wait_for(task, timeout=float(timeout))
            except TimeoutError as error:
                if not task.cancelled():
                    raise BelgieSandboxExecutionError(f"Belgie script execution failed:\n{error}") from error
                await _drain_cancelled_task(task)
                raise BelgieSandboxTimeoutError(
                    f"Belgie script execution timed out after {timeout} seconds."
                ) from error
            except asyncio.CancelledError:
                await _drain_cancelled_task(task)
                raise
        except BelgieSandboxTimeoutError:
            raise
        except BelgieSandboxExecutionError:
            raise
        except belgie_error as error:
            raise BelgieSandboxExecutionError(f"Belgie script execution failed:\n{error}") from error
        except (TypeError, ValueError) as error:
            raise BelgieSandboxExecutionError(f"Belgie script returned an invalid JSON value:\n{error}") from error

    async def _run_script(
        self,
        active_runtime: _AsyncRuntime,
        belgie: _BelgieModule,
        script: object,
        source: str,
    ) -> JsonOutput:
        result = await active_runtime(script)()
        if not is_render_request(result):
            return result
        return await self._render_html(belgie, source)

    async def _render_html(self, belgie: _BelgieModule, source: str) -> JsonOutput:
        render_runtime = self._render_runtime
        workspace = self._workspace
        if render_runtime is None or workspace is None:
            raise BelgieSandboxExecutionError(
                "@belgie/render requested HTML, but this session has no renderer side-channel "
                "(custom `runtime=` does not mediate rendering)."
            )
        if self._render_script is None:
            self._render_script = belgie.Script.from_file(workspace / RENDER_HOST_ENTRY)
        url = (workspace / INLINE_MODULE_FILENAME).resolve().as_uri()
        return await render_runtime(self._render_script)(source, url)


__all__: tuple[str, ...] = (
    "DEFAULT_MAX_OLD_GENERATION_SIZE_MB",
    "DEFAULT_RENDER_DEPENDENCIES",
    "DEFAULT_RENDER_SPECIFIER",
    "DEFAULT_TIMEOUT",
    "DEFAULT_VITE_SYS_PERMISSIONS",
    "INLINE_MODULE_FILENAME",
    "RENDER_HOST_ENTRY",
    "RENDER_REQUEST_KEY",
    "BelgieSandboxError",
    "BelgieSandboxExecutionError",
    "BelgieSandboxSession",
    "BelgieSandboxTimeoutError",
    "BelgieSandboxUnavailableError",
    "is_render_request",
)
