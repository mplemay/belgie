from __future__ import annotations

import asyncio
import importlib
import math
import re
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING, Final, Protocol, Self, runtime_checkable

import anyio

if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine
    from types import TracebackType

DEFAULT_TIMEOUT: Final[float] = 30.0
DEFAULT_MAX_OLD_GENERATION_SIZE_MB: Final[int] = 128
DEFAULT_RENDER_SPECIFIER: Final[str] = "npm:@belgie/vite"
DEFAULT_RENDER_DEPENDENCIES: Final[dict[str, str]] = {
    "@belgie/vite": DEFAULT_RENDER_SPECIFIER,
    "react": "npm:react@19.2.8",
    "react-dom": "npm:react-dom@19.2.8",
}
DEFAULT_VITE_SYS_PERMISSIONS: Final[tuple[str, ...]] = (
    "homedir",
    "uid",
    "gid",
    "cpus",
    "osRelease",
    "systemMemoryInfo",
)
MISSING_BELGIE: Final[str] = (
    'Belgie Sandbox requires Belgie and Python 3.12-3.14. Install it with `uv add "belgie[pydantic-ai]"`.'
)
_SCOPED_PACKAGE: Final[re.Pattern[str]] = re.compile(
    r"^(@[^@/]+/[^@/]+)(?:@[^@]+)?$",
)
_UNSCOPED_PACKAGE: Final[re.Pattern[str]] = re.compile(
    r"^([^@/]+)(?:@[^@]+)?$",
)

type JsonPrimitive = bool | int | float | str | None
type JsonOutput = JsonPrimitive | list["JsonOutput"] | dict[str, "JsonOutput"]


class _EnvironmentOptionsFactory(Protocol):
    def __call__(self, *, allow_remote: bool, no_npm: bool) -> object: ...


class _RuntimePermissionsFactory(Protocol):
    def __call__(  # noqa: PLR0913
        self,
        *,
        allow_read: Sequence[str] | None = None,
        allow_net: Sequence[str] | None = None,
        allow_env: Sequence[str] | None = None,
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


class _CommandFactory(Protocol):
    def __call__(
        self,
        name: str,
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        module: bool = False,
    ) -> object: ...


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
    Command: _CommandFactory


@runtime_checkable
class _BelgieErrorsModule(Protocol):
    BelgieError: type[Exception]


def _load_belgie() -> _BelgieModule:
    try:
        module = importlib.import_module("belgie")
    except ImportError as error:
        raise BelgieSandboxUnavailableError(MISSING_BELGIE) from error
    if not isinstance(module, _BelgieModule):
        message = "The installed Belgie package does not provide the required runtime API."
        raise BelgieSandboxUnavailableError(message)
    return module


def _load_belgie_error() -> type[Exception]:
    try:
        module = importlib.import_module("belgie.errors")
    except ImportError as error:
        raise BelgieSandboxUnavailableError(MISSING_BELGIE) from error
    if not isinstance(module, _BelgieErrorsModule):
        message = "The installed Belgie package does not provide its public error API."
        raise BelgieSandboxUnavailableError(message)
    return module.BelgieError


def package_name_from_specifier(specifier: str) -> str:
    if type(specifier) is not str or not specifier:
        message = f"specifier must be a non-empty string, got {specifier!r}."
        raise ValueError(message)
    if specifier.startswith("jsr:") or specifier.removeprefix("npm:").startswith("jsr:"):
        message = f"JSR package specifiers are not supported, got {specifier!r}."
        raise ValueError(message)
    rest = specifier.removeprefix("npm:")
    if rest.startswith("@"):
        match = _SCOPED_PACKAGE.fullmatch(rest)
        if match is None:
            message = f"Could not parse scoped package name from {specifier!r}."
            raise ValueError(message)
        return match.group(1)
    match = _UNSCOPED_PACKAGE.fullmatch(rest)
    if match is None:
        message = f"Could not parse package name from {specifier!r}."
        raise ValueError(message)
    return match.group(1)


def _dependency_specifier(specifier: str) -> str:
    if specifier.startswith("npm:"):
        return specifier
    return f"npm:{specifier}"


def _validate_plugins(plugins: object) -> tuple[str, ...]:
    if isinstance(plugins, (str, bytes)) or not isinstance(plugins, Sequence):
        message = f"plugins must be a sequence of non-empty strings, got {plugins!r}."
        raise TypeError(message)
    validated: list[str] = []
    for plugin in plugins:
        if type(plugin) is not str or not plugin:
            message = f"plugins must be a sequence of non-empty strings, got {plugins!r}."
            raise ValueError(message)
        validated.append(plugin)
    return tuple(validated)


def _render_dependencies(plugins: Sequence[str]) -> dict[str, str]:
    dependencies = dict(DEFAULT_RENDER_DEPENDENCIES)
    for plugin in plugins:
        dependencies[package_name_from_specifier(plugin)] = _dependency_specifier(plugin)
    return dependencies


def _resolved_path(path: str | Path) -> Path:
    return Path(path).resolve()


class BelgieSandboxError(RuntimeError):
    pass


class BelgieSandboxExecutionError(BelgieSandboxError):
    pass


class BelgieSandboxTimeoutError(BelgieSandboxExecutionError):
    pass


class BelgieSandboxUnavailableError(BelgieSandboxError):
    pass


async def _drain_cancelled_task(task: asyncio.Task[object]) -> None:
    task.cancel()
    with suppress(BaseException):
        await task


class BelgieSandboxSession:
    def __init__(  # noqa: PLR0913
        self,
        *,
        allow_package_imports: bool = False,
        allow_network: bool = False,
        enable_rendering: bool = False,
        plugins: Sequence[str] = (),
        max_old_generation_size_mb: int | None = DEFAULT_MAX_OLD_GENERATION_SIZE_MB,
        runtime: _RuntimeContext | None = None,
    ) -> None:
        for name, value in (
            ("allow_package_imports", allow_package_imports),
            ("allow_network", allow_network),
            ("enable_rendering", enable_rendering),
        ):
            if type(value) is not bool:
                message = f"{name} must be a bool, got {value!r}."
                raise ValueError(message)
        validated_plugins = _validate_plugins(plugins)
        if validated_plugins and not enable_rendering:
            message = "plugins requires enable_rendering=True."
            raise ValueError(message)
        if max_old_generation_size_mb is not None and (
            type(max_old_generation_size_mb) is not int or max_old_generation_size_mb <= 0
        ):
            message = (
                f"max_old_generation_size_mb must be a positive integer or None, got {max_old_generation_size_mb!r}."
            )
            raise ValueError(message)
        if runtime is not None:
            conflicts = [
                name
                for name, value, default in (
                    ("allow_package_imports", allow_package_imports, False),
                    ("allow_network", allow_network, False),
                    ("enable_rendering", enable_rendering, False),
                    ("plugins", validated_plugins, ()),
                    (
                        "max_old_generation_size_mb",
                        max_old_generation_size_mb,
                        DEFAULT_MAX_OLD_GENERATION_SIZE_MB,
                    ),
                )
                if value != default
            ]
            if conflicts:
                message = (
                    f"{', '.join(conflicts)} cannot be combined with `runtime`, which already defines "
                    "the Belgie environment and runtime options."
                )
                raise ValueError(message)
        self._allow_package_imports = allow_package_imports
        self._allow_network = allow_network
        self._enable_rendering = enable_rendering
        self._plugins = validated_plugins
        self._max_old_generation_size_mb = max_old_generation_size_mb
        self._configured_runtime = runtime
        self._entering = False
        self._runtime_context: _RuntimeContext | None = None
        self._render_runtime_context: _RuntimeContext | None = None
        self._environment_context: _EnvironmentContext | None = None
        self._temporary_directory: TemporaryDirectory[str] | None = None
        self._active_runtime: _AsyncRuntime | None = None
        self._render_runtime: _AsyncRuntime | None = None
        self._workspace: Path | None = None

    @property
    def is_open(self) -> bool:
        return self._active_runtime is not None

    @property
    def workspace(self) -> Path | None:
        return self._workspace

    async def __aenter__(self) -> Self:  # noqa: C901, PLR0912, PLR0915
        if self._entering or any(
            resource is not None
            for resource in (
                self._runtime_context,
                self._render_runtime_context,
                self._environment_context,
                self._temporary_directory,
            )
        ):
            message = (
                "The session is already open or has pending cleanup; close it before entering again. "
                "Use a separate session per concurrent context."
            )
            raise BelgieSandboxError(message)
        self._entering = True
        try:
            try:
                asyncio.get_running_loop()
            except RuntimeError as error:
                message = "Belgie Sandbox requires an asyncio event loop."
                raise BelgieSandboxError(message) from error
            belgie = _load_belgie()
            try:
                if self._configured_runtime is not None:
                    runtime_context = self._configured_runtime
                    active_runtime = await runtime_context.__aenter__()
                    self._runtime_context = runtime_context
                    if not isinstance(active_runtime, _AsyncRuntime):
                        message = "The installed Belgie package returned an incompatible runtime."
                        raise BelgieSandboxUnavailableError(message)  # noqa: TRY301
                    self._active_runtime = active_runtime
                else:
                    temporary_directory = TemporaryDirectory(prefix="belgie-sandbox-")
                    self._temporary_directory = temporary_directory
                    workspace = _resolved_path(temporary_directory.name)
                    self._workspace = workspace
                    packages_enabled = self._allow_package_imports or self._enable_rendering
                    dependencies = _render_dependencies(self._plugins) if self._enable_rendering else None
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
                        message = "The installed Belgie package returned an incompatible environment."
                        raise BelgieSandboxUnavailableError(message)  # noqa: TRY301
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
                        message = "The installed Belgie package returned an incompatible runtime."
                        raise BelgieSandboxUnavailableError(message)  # noqa: TRY301
                    self._active_runtime = active_runtime
                    if self._enable_rendering:
                        render_runtime_context = belgie.Runtime(
                            env=active_environment,
                            options=belgie.RuntimeOptions(
                                max_old_generation_size_mb=self._max_old_generation_size_mb,
                                permissions=belgie.RuntimePermissions(
                                    allow_env=[],
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
                            message = "The installed Belgie package returned an incompatible renderer runtime."
                            raise BelgieSandboxUnavailableError(message)  # noqa: TRY301
                        self._render_runtime = render_runtime
            except BaseException as error:
                try:
                    await self._close_resources(None, None, None)
                except BaseException as cleanup_error:
                    if isinstance(error, Exception):
                        message = f"Could not start the Belgie sandbox: {error}. Cleanup also failed: {cleanup_error}"
                        raise BelgieSandboxUnavailableError(message) from error
                    raise error from cleanup_error
                if isinstance(error, Exception):
                    message = f"Could not start the Belgie sandbox: {error}"
                    raise BelgieSandboxUnavailableError(message) from error
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

    async def _close_resources(  # noqa: C901, PLR0912
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
                except BaseException as error:  # noqa: BLE001
                    first_error = first_error or error
                else:
                    self._render_runtime_context = None
                    self._render_runtime = None
            runtime_context = self._runtime_context
            if runtime_context is not None:
                try:
                    await runtime_context.__aexit__(exc_type, exc, traceback)
                except BaseException as error:  # noqa: BLE001
                    first_error = first_error or error
                else:
                    self._runtime_context = None
                    self._active_runtime = None
            environment_context = self._environment_context
            if environment_context is not None:
                try:
                    await environment_context.__aexit__(exc_type, exc, traceback)
                except BaseException as error:  # noqa: BLE001
                    first_error = first_error or error
                else:
                    self._environment_context = None
            temporary_directory = self._temporary_directory
            if temporary_directory is not None:
                try:
                    temporary_directory.cleanup()
                except BaseException as error:  # noqa: BLE001
                    first_error = first_error or error
                else:
                    self._temporary_directory = None
                    self._workspace = None

        self._entering = False
        if first_error is not None:
            raise first_error

    async def close(self) -> None:
        await self.__aexit__(None, None, None)

    async def run_script(self, source: str, *, timeout: float = DEFAULT_TIMEOUT) -> JsonOutput:  # noqa: ASYNC109, C901
        active_runtime = self._active_runtime
        if active_runtime is None:
            message = "The Belgie sandbox session is not open."
            raise BelgieSandboxError(message)
        if type(source) is not str:
            message = f"source must be a string, got {type(source).__name__}."
            raise TypeError(message)
        if type(timeout) is bool or not math.isfinite(timeout) or timeout <= 0:
            message = f"timeout must be a positive finite number, got {timeout!r}."
            raise ValueError(message)
        belgie = _load_belgie()
        belgie_error = _load_belgie_error()
        try:
            script = belgie.Script(source)
            task = asyncio.create_task(self._run_script(active_runtime, script))
            try:
                return await asyncio.wait_for(task, timeout=float(timeout))
            except TimeoutError as error:
                if not task.cancelled():
                    message = f"Belgie script execution failed:\n{error}"
                    raise BelgieSandboxExecutionError(message) from error
                await _drain_cancelled_task(task)
                message = f"Belgie script execution timed out after {timeout} seconds."
                raise BelgieSandboxTimeoutError(message) from error
            except asyncio.CancelledError:
                await _drain_cancelled_task(task)
                raise
        except BelgieSandboxTimeoutError:
            raise
        except BelgieSandboxExecutionError:
            raise
        except belgie_error as error:
            message = f"Belgie script execution failed:\n{error}"
            raise BelgieSandboxExecutionError(message) from error
        except (TypeError, ValueError) as error:
            message = f"Belgie script returned an invalid JSON value:\n{error}"
            raise BelgieSandboxExecutionError(message) from error

    async def render_widget(self, source: str, *, timeout: float = DEFAULT_TIMEOUT) -> str:  # noqa: ASYNC109, C901
        render_runtime = self._render_runtime
        workspace = self._workspace
        if self._active_runtime is None:
            message = "The Belgie sandbox session is not open."
            raise BelgieSandboxError(message)
        if render_runtime is None or workspace is None or not self._enable_rendering:
            message = (
                "Widget rendering is unavailable: enable_rendering must be True on an owned session "
                "(custom `runtime=` does not provide a renderer)."
            )
            raise BelgieSandboxError(message)
        if type(source) is not str:
            message = f"source must be a string, got {type(source).__name__}."
            raise TypeError(message)
        if type(timeout) is bool or not math.isfinite(timeout) or timeout <= 0:
            message = f"timeout must be a positive finite number, got {timeout!r}."
            raise ValueError(message)
        belgie = _load_belgie()
        belgie_error = _load_belgie_error()
        widget_path = workspace / "widget.tsx"
        out_path = workspace / "widget.html"
        widget_path.write_text(source, encoding="utf-8")
        argv = ["--widget", str(widget_path), "--out", str(out_path)]
        for plugin in self._plugins:
            argv.extend(("--plugins", plugin))
        try:
            task = asyncio.create_task(render_runtime(belgie.Command("@belgie/vite"))(*argv))
            try:
                await asyncio.wait_for(task, timeout=float(timeout))
            except TimeoutError as error:
                if not task.cancelled():
                    message = f"Belgie widget rendering failed:\n{error}"
                    raise BelgieSandboxExecutionError(message) from error
                await _drain_cancelled_task(task)
                message = f"Belgie widget rendering timed out after {timeout} seconds."
                raise BelgieSandboxTimeoutError(message) from error
            except asyncio.CancelledError:
                await _drain_cancelled_task(task)
                raise
            return out_path.read_text(encoding="utf-8")
        except BelgieSandboxTimeoutError:
            raise
        except BelgieSandboxExecutionError:
            raise
        except belgie_error as error:
            message = f"Belgie widget rendering failed:\n{error}"
            raise BelgieSandboxExecutionError(message) from error
        finally:
            widget_path.unlink(missing_ok=True)
            out_path.unlink(missing_ok=True)

    async def _run_script(
        self,
        active_runtime: _AsyncRuntime,
        script: object,
    ) -> JsonOutput:
        return await active_runtime(script)()


__all__: tuple[str, ...] = (
    "DEFAULT_MAX_OLD_GENERATION_SIZE_MB",
    "DEFAULT_RENDER_DEPENDENCIES",
    "DEFAULT_RENDER_SPECIFIER",
    "DEFAULT_TIMEOUT",
    "DEFAULT_VITE_SYS_PERMISSIONS",
    "BelgieSandboxError",
    "BelgieSandboxExecutionError",
    "BelgieSandboxSession",
    "BelgieSandboxTimeoutError",
    "BelgieSandboxUnavailableError",
    "package_name_from_specifier",
)
