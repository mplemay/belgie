from collections.abc import Awaitable, Coroutine, Iterable, Mapping
from os import PathLike
from pathlib import Path
from types import TracebackType
from typing import Any, Literal, Self, overload

type JsonPrimitive = None | bool | int | float | str
type JsonInput = JsonPrimitive | list[JsonInput] | tuple[JsonInput, ...] | dict[str, JsonInput]
type JsonOutput = JsonPrimitive | list[JsonOutput] | dict[str, JsonOutput]
type JsonObject = dict[str, JsonOutput]
type JsonArray = list[JsonOutput]
type CacheSetting = Literal["use", "reload", "only"]
type JsonImportMode = Literal["with_attribute", "always"]
type NodeModulesDirMode = Literal["auto", "manual", "none"]
type NodeModulesLinkerMode = Literal["isolated", "hoisted"]
type NpmCachingMode = Literal["eager", "lazy", "manual"]
type WorkerLogLevel = Literal["error", "warn", "info", "debug"]

class BelgieError(Exception): ...
class BelgieRuntimeError(BelgieError): ...
class BelgieModuleError(BelgieError): ...
class BelgieJavaScriptError(BelgieError): ...

class EnvironmentInstallResult:
    @property
    def lockfile(self) -> str: ...
    @property
    def dependencies(self) -> int: ...

class EnvironmentUpdateChange:
    @property
    def name(self) -> str: ...
    @property
    def previous(self) -> str: ...
    @property
    def updated(self) -> str: ...

class EnvironmentUpdateResult:
    @property
    def lockfile(self) -> str: ...
    @property
    def changes(self) -> list[EnvironmentUpdateChange]: ...

class SyncEnvironment:
    @property
    def path(self) -> Path: ...
    def lock(self, *, lockfile: str | PathLike[str] | None = None) -> EnvironmentInstallResult: ...
    def install(self) -> EnvironmentInstallResult: ...
    def update(
        self,
        packages: Iterable[str] | None = None,
        *,
        latest: bool = False,
        lockfile_only: bool = False,
    ) -> EnvironmentUpdateResult: ...

class AsyncEnvironment:
    @property
    def path(self) -> Path: ...
    def lock(self, *, lockfile: str | PathLike[str] | None = None) -> Awaitable[EnvironmentInstallResult]: ...
    def install(self) -> Awaitable[EnvironmentInstallResult]: ...
    def update(
        self,
        packages: Iterable[str] | None = None,
        *,
        latest: bool = False,
        lockfile_only: bool = False,
    ) -> Awaitable[EnvironmentUpdateResult]: ...

class Script[**P, R]:
    def __init__(self, content: str) -> None: ...
    @property
    def content(self) -> str: ...
    @property
    def filename(self) -> Path | None: ...
    @classmethod
    def from_file(cls: type[Self], path: str | PathLike[str]) -> Self: ...

class SyncRunner[**P, R]:
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> R: ...

class AsyncRunner[**P, R]:
    def __call__(self, *args: P.args, **kwargs: P.kwargs) -> Coroutine[Any, Any, R]: ...

class Command:
    def __init__(
        self,
        name: str,
        *,
        cwd: str | PathLike[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> None: ...

class SyncCommandRunner:
    def __call__(self, *args: str) -> None: ...

class AsyncCommandRunner:
    def __call__(self, *args: str) -> Coroutine[Any, Any, None]: ...

class SyncRuntime:
    @overload
    def __call__[**P, R](self, target: Script[P, R]) -> SyncRunner[P, R]: ...
    @overload
    def __call__(self, target: Command) -> SyncCommandRunner: ...

class AsyncRuntime:
    @overload
    def __call__[**P, R](self, target: Script[P, R]) -> AsyncRunner[P, R]: ...
    @overload
    def __call__(self, target: Command) -> AsyncCommandRunner: ...

class RuntimePermissions:
    def __init__(
        self,
        *,
        allow_env: Iterable[str] | None = None,
        deny_env: Iterable[str] | None = None,
        ignore_env: Iterable[str] | None = None,
        allow_net: Iterable[str] | None = None,
        deny_net: Iterable[str] | None = None,
        allow_ffi: Iterable[str] | None = None,
        deny_ffi: Iterable[str] | None = None,
        allow_read: Iterable[str] | None = None,
        deny_read: Iterable[str] | None = None,
        ignore_read: Iterable[str] | None = None,
        allow_run: Iterable[str] | None = None,
        deny_run: Iterable[str] | None = None,
        allow_sys: Iterable[str] | None = None,
        deny_sys: Iterable[str] | None = None,
        allow_write: Iterable[str] | None = None,
        deny_write: Iterable[str] | None = None,
        allow_import: Iterable[str] | None = None,
        deny_import: Iterable[str] | None = None,
        prompt: bool = False,
    ) -> None: ...
    @classmethod
    def all(cls) -> Self: ...
    @classmethod
    def none(cls, *, prompt: bool = False) -> Self: ...

class RuntimeOptions:
    def __init__(
        self,
        *,
        max_old_generation_size_mb: int | None = None,
        max_young_generation_size_mb: int | None = None,
        code_range_size_mb: int | None = None,
        permissions: RuntimePermissions | None = None,
        seed: int | None = None,
        location: str | None = None,
        log_level: WorkerLogLevel | None = None,
        enable_testing_features: bool = False,
        enable_raw_imports: bool = False,
        disable_offscreen_canvas: bool = False,
        trace_ops: Iterable[str] | None = None,
    ) -> None: ...

class EnvironmentOptions:
    def __init__(
        self,
        *,
        cache_setting: CacheSetting = "use",
        reload: Iterable[str] | None = None,
        allow_remote: bool = True,
        allow_json_imports: JsonImportMode = "with_attribute",
        node_modules_dir: NodeModulesDirMode | None = None,
        node_modules_linker: NodeModulesLinkerMode | None = None,
        npm_caching: NpmCachingMode = "eager",
        no_npm: bool = False,
        clean_on_install: bool = True,
        production: bool = False,
        skip_types: bool = False,
        unsafely_ignore_certificate_errors: bool | Iterable[str] | None = None,
        import_package_lockfile: bool = False,
        minimum_dependency_age_minutes: int | None = None,
    ) -> None: ...

class Environment:
    def __init__(
        self,
        dependencies: Mapping[str, str] | None = None,
        *,
        path: str | PathLike[str] | None = None,
        lockfile: str | PathLike[str] | None = None,
        cache: str | PathLike[str] | None = None,
        options: EnvironmentOptions | None = None,
    ) -> None: ...
    @property
    def path(self) -> Path: ...
    def __enter__(self) -> SyncEnvironment: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
    async def __aenter__(self) -> AsyncEnvironment: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...

class Runtime:
    def __init__(
        self,
        *,
        env: Environment | SyncEnvironment | AsyncEnvironment | None = None,
        options: RuntimeOptions | None = None,
    ) -> None: ...
    @classmethod
    def from_folder(
        cls: type[Self],
        path: str | PathLike[str],
        *,
        options: RuntimeOptions | None = None,
    ) -> Self: ...
    def __enter__(self) -> SyncRuntime: ...
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
    async def __aenter__(self) -> AsyncRuntime: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None: ...
